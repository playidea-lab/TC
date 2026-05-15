"""GET /ready readiness probe 검증."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from the_commons.db import session as session_module
from the_commons.main import app


def test_health_returns_ok_without_dependencies() -> None:
    """liveness — DB 다운돼도 통과해야 한다 (process 살아있음만)."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_returns_200_when_db_select_succeeds(monkeypatch) -> None:
    """readiness — DB SELECT 1 통과 시 200 + checks.database='ok'."""

    cursor = MagicMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.execute = AsyncMock()

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)

    @asynccontextmanager
    async def fake_get_connection() -> AsyncIterator[MagicMock]:
        yield conn

    monkeypatch.setattr(session_module, "get_connection", fake_get_connection)

    # health module이 import 시점에 get_connection 캐시했을 수 있어 직접 교체
    from the_commons.api import health as health_module

    monkeypatch.setattr(health_module, "get_connection", fake_get_connection)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


def test_ready_returns_503_when_db_fails(monkeypatch) -> None:
    """readiness — DB connection 실패 시 503."""

    @asynccontextmanager
    async def failing_get_connection() -> AsyncIterator[MagicMock]:
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    from the_commons.api import health as health_module

    monkeypatch.setattr(health_module, "get_connection", failing_get_connection)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert "database" in response.json()["detail"]["reason"]
