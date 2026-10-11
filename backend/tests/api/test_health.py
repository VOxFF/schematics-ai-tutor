from fastapi.testclient import TestClient

from app.main import app


def test_health(monkeypatch):
    monkeypatch.delenv("SCHEMATICS_COMMIT", raising=False)
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "commit": None}


def test_health_reports_the_deployed_commit(monkeypatch):
    monkeypatch.setenv("SCHEMATICS_COMMIT", "abc123")
    assert TestClient(app).get("/api/health").json()["commit"] == "abc123"
