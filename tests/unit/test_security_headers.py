"""SecurityHeadersMiddleware — OWASP baseline 헤더 응답 부착 (E.7)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from the_commons.logging_config import SecurityHeadersMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    return app


def test_response_includes_nosniff_and_frame_deny() -> None:
    """모든 응답에 nosniff·DENY·no-referrer 헤더 포함."""
    with TestClient(_app()) as client:
        response = client.get("/ping")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_setdefault_preserves_explicit_endpoint_headers() -> None:
    """endpoint가 명시한 헤더는 setdefault라 덮어쓰지 않음."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/custom")
    async def custom():
        from fastapi import Response

        return Response(
            content='{"ok":true}',
            media_type="application/json",
            headers={"X-Frame-Options": "SAMEORIGIN"},
        )

    with TestClient(app) as client:
        response = client.get("/custom")

    # endpoint 값 유지
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    # 나머지 default는 적용
    assert response.headers["X-Content-Type-Options"] == "nosniff"
