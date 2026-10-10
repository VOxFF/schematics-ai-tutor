from fastapi.testclient import TestClient

from app.main import References, app, get_claude, get_config, get_references, get_usage_log
from app.usage_log import UsageLog
from tests.conftest import FakeClaude, as_claude_output, load_example, text_response


REFERENCES = References()


def client_with(claude, config):
    app.dependency_overrides = {
        get_claude: lambda: claude,
        get_config: lambda: config,
        get_usage_log: lambda: UsageLog(None),
        get_references: lambda: REFERENCES,
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
