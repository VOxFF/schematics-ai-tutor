from fastapi.testclient import TestClient

import pytest

pytestmark = pytest.mark.usefixtures("any_level")

from app.task_generation import GenerationResult
from app.main import References, app, get_claude, get_config, get_limits, get_references, get_task_cache, get_usage_log
from app.rate_limits import RateLimiter
from app.usage_log import UsageLog
from tests.conftest import FakeClaude, as_claude_output, load_example, text_response


REFERENCES = References()


def client_with(claude, config, cache=None, limits=None):
    app.dependency_overrides = {
        get_claude: lambda: claude,
        get_config: lambda: config,
        get_usage_log: lambda: UsageLog(None),
        get_references: lambda: REFERENCES,
        get_task_cache: lambda: cache,  # None: generate on request; the cache has its own tests
        get_limits: lambda: limits or RateLimiter(config["rate_limits"]),
    }
    return TestClient(app)


def test_generate_returns_a_level(config):
    fake = FakeClaude([text_response(as_claude_output(load_example()))])
    response = client_with(fake, config).post("/api/tasks/generate", json={"skill_level": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["level"]["order"] == 3
    assert body["level"]["board"]["inventory"][0]["id"] == "R2"
    assert body["difficulty"] == 3 and body["attempts"] == 1
    assert body["level"]["id"] in REFERENCES  # reference kept server-side for the tutor
    # A new learner: the task brings topics they haven't met, so the welcome teaches.
    assert body["welcome"]["text"] == load_example()["welcome"]
    assert body["welcome"]["kind"] == "knowledge" and body["welcome"]["icon"] == "📘"


def test_the_welcome_is_feedback_when_the_task_brings_nothing_new(config):
    from app.learner_profile import join
    from tests.conftest import example_level

    level, _ = example_level()
    profile = {"topics": []}
    join(profile, {"curriculum": {"level": 8}}, level["board"], 20)  # every topic this task could bring
    fake = FakeClaude([text_response(as_claude_output(load_example()))])
    response = client_with(fake, config).post("/api/tasks/generate", json={"skill_level": 3, "profile": profile})
    assert response.json()["welcome"]["kind"] == "feedback"


def test_generate_serves_from_the_cache(config):
    class Cache:
        def __init__(self):
            self.requested = []

        async def get(self, progress):
            self.requested.append(progress)
            spec = load_example()
            level = {"id": "gen-cached", "order": progress["skill_level"], "title": "t", "board": {}}
            return GenerationResult(spec=spec, level=level, attempts=1)

    cache = Cache()
    response = client_with(FakeClaude([]), config, cache).post("/api/tasks/generate", json={"skill_level": 2})
    assert response.status_code == 200 and response.json()["level"]["id"] == "gen-cached"
    assert cache.requested == [{"skill_level": 2, "history": []}]
    assert "gen-cached" in REFERENCES


def test_generate_without_claude_is_503(config):
    response = client_with(None, config).post("/api/tasks/generate", json={})
    assert response.status_code == 503


def test_generate_failure_is_502_with_errors(config):
    bad = as_claude_output(load_example())
    bad["removed_ids"] = []
    fake = FakeClaude([text_response(bad), text_response(bad)])
    response = client_with(fake, config).post("/api/tasks/generate", json={})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["attempts"] == 2
    assert detail["message"] == "Sorry, I couldn't create a valid task after 2 attempts. Please try again."


def teardown_function():
    app.dependency_overrides = {}


def test_generate_is_limited_per_ip(config):
    limits = RateLimiter({**config["rate_limits"], "task_generation": {"per_ip_per_hour": 1}})
    fake = FakeClaude([text_response(as_claude_output(load_example()))])
    client = client_with(fake, config, limits=limits)
    assert client.post("/api/tasks/generate", json={"skill_level": 3}).status_code == 200
    refused = client.post("/api/tasks/generate", json={"skill_level": 3})
    assert refused.status_code == 429
    assert "try again in 60 min" in refused.json()["detail"]
    assert refused.headers["retry-after"] == "3600"


def test_generate_stops_at_the_claude_budget(config):
    limits = RateLimiter(config["rate_limits"])
    limits.budget.spend(limits.budget.usd_per_day)
    fake = FakeClaude([])
    response = client_with(fake, config, limits=limits).post("/api/tasks/generate", json={"skill_level": 3})
    assert response.status_code == 429 and "today's limit" in response.json()["detail"]
    assert fake.requests == []


def test_rest_requests_are_limited_per_ip_but_not_health(config):
    app.state.limits = RateLimiter({**config["rate_limits"], "rest": {"requests_per_ip_per_min": 1}})
    try:
        client = client_with(None, config)
        assert client.post("/api/tasks/generate", json={"skill_level": 1}).status_code == 503  # no Claude
        assert client.post("/api/tasks/generate", json={"skill_level": 1}).status_code == 429
        assert client.get("/api/health").status_code == 200
    finally:
        del app.state.limits
