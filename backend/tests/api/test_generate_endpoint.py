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

        async def get(self, progress, produce=True):
            self.requested.append((progress, produce))
            spec = load_example()
            level = {"id": "gen-cached", "order": progress["skill_level"], "title": "t", "board": {}}
            return GenerationResult(spec=spec, level=level, attempts=1)

    cache = Cache()
    response = client_with(FakeClaude([]), config, cache).post("/api/tasks/generate", json={"skill_level": 2})
    assert response.status_code == 200 and response.json()["level"]["id"] == "gen-cached"
    assert response.json()["source"] == "generated"
    assert cache.requested == [({"skill_level": 2, "history": []}, True)]
    assert "gen-cached" in REFERENCES


def test_a_cached_task_is_served_even_when_claude_is_down(config):
    class Cache:
        async def get(self, progress, produce=True):
            assert not produce  # nothing new is generated while Claude is down
            return GenerationResult(spec=load_example(), level={"id": "gen-cached-2", "title": "t"}, attempts=1)

    down = FakeClaude([])
    down.down = True
    response = client_with(down, config, Cache()).post("/api/tasks/generate", json={"skill_level": 2})
    assert response.json()["level"]["id"] == "gen-cached-2" and response.json()["source"] == "generated"


def served_from_the_pack(response):
    body = response.json()
    assert response.status_code == 200 and body["source"] == "fallback" and body["level"]["source"] == "fallback"
    assert body["level"]["title"] == load_example()["title"] and body["level"]["id"] in REFERENCES
    assert body["welcome"]["text"] == load_example()["welcome"]
    return body


def test_without_claude_the_pack_is_served(config, pack):
    body = served_from_the_pack(client_with(None, config).post("/api/tasks/generate", json={"skill_level": 3}))
    assert body["level"]["order"] == 3 and body["attempts"] == 0


def test_while_claude_is_down_the_pack_is_served_without_a_call(config, pack):
    down = FakeClaude([])
    down.down = True
    served_from_the_pack(client_with(down, config).post("/api/tasks/generate", json={"skill_level": 3}))
    assert down.requests == []


def test_a_failed_generation_falls_back_to_the_pack(config, pack):
    bad = as_claude_output(load_example())
    bad["removed_ids"] = []
    fake = FakeClaude([text_response(bad), text_response(bad)])
    served_from_the_pack(client_with(fake, config).post("/api/tasks/generate", json={}))
    assert len(fake.requests) == 2


def test_without_a_pack_a_failure_is_502(config, pack):
    (pack / "skill-1.json").unlink()
    response = client_with(None, config).post("/api/tasks/generate", json={})
    assert response.status_code == 502
    assert response.json()["detail"]["message"] == "Sorry, I couldn't create a task right now. Please try again."


def teardown_function():
    app.dependency_overrides = {}


def test_over_the_ip_limit_the_pack_is_served(config, pack):
    limits = RateLimiter({**config["rate_limits"], "task_generation": {"per_ip_per_hour": 1}})
    fake = FakeClaude([text_response(as_claude_output(load_example()))])
    client = client_with(fake, config, limits=limits)
    assert client.post("/api/tasks/generate", json={"skill_level": 3}).json()["source"] == "generated"
    served_from_the_pack(client.post("/api/tasks/generate", json={"skill_level": 3}))
    assert len(fake.requests) == 1


def test_at_the_claude_budget_the_pack_is_served(config, pack):
    limits = RateLimiter(config["rate_limits"])
    limits.budget.spend(limits.budget.usd_per_day)
    fake = FakeClaude([])
    served_from_the_pack(client_with(fake, config, limits=limits).post("/api/tasks/generate", json={"skill_level": 3}))
    assert fake.requests == []


def test_rest_requests_are_limited_per_ip_but_not_health(config, pack):
    app.state.limits = RateLimiter({**config["rate_limits"], "rest": {"requests_per_ip_per_min": 1}})
    try:
        client = client_with(None, config)
        assert client.post("/api/tasks/generate", json={"skill_level": 1}).status_code == 200  # from the pack
        assert client.post("/api/tasks/generate", json={"skill_level": 1}).status_code == 429
        assert client.get("/api/health").status_code == 200
    finally:
        del app.state.limits
