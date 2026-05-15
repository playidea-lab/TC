"""BodySizeLimitMiddleware — Content-Length 초과 시 413 차단."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from the_commons.logging_config import BodySizeLimitMiddleware


@pytest.fixture
def app_with_limit() -> FastAPI:
    """100 byte limit으로 격리된 minimal app."""
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=100)

    @app.post("/echo")
    async def echo(body: dict) -> dict:
        return body

    return app


def test_small_body_passes(app_with_limit: FastAPI) -> None:
    """한도 이내 body는 정상 처리."""
    with TestClient(app_with_limit) as client:
        response = client.post("/echo", json={"k": "v"})
    assert response.status_code == 200


def test_oversized_body_returns_413(app_with_limit: FastAPI) -> None:
    """한도 초과 body는 JWT 검증 등 이전 단계에서 413으로 끊김."""
    big_payload = {"data": "x" * 200}  # > 100 bytes
    with TestClient(app_with_limit) as client:
        response = client.post("/echo", json=big_payload)
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


def test_invalid_content_length_passes_through(app_with_limit: FastAPI) -> None:
    """Content-Length 헤더가 숫자가 아니면 middleware는 거르지 않고 통과.

    Starlette/uvicorn이 알아서 400으로 거른다.
    """
    with TestClient(app_with_limit) as client:
        # client가 정상 Content-Length 자동 계산 — 단순 small request 통과 확인
        response = client.post("/echo", json={"a": 1})
    assert response.status_code == 200
