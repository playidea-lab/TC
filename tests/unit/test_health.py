"""Health endpoint 동작 검증."""

from fastapi.testclient import TestClient


def test_health_with_running_app_returns_ok(client: TestClient) -> None:
    """GET /health가 200 + status=ok + version 필드를 반환해야 함."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
