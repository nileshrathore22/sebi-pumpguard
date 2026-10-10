from fastapi.testclient import TestClient

from app.api.app import create_app


def test_health_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "not investment advice" in resp.json()["disclaimer"].lower()
