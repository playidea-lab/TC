"""structlog 기반 JSON logging + request_id middleware.

production은 LOG_FORMAT=json, dev는 console(컬러). request_id가 응답 헤더
X-Request-ID로 echo되므로 사용자가 incident report 시 trace 가능.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from the_commons.settings import settings


def configure_logging() -> None:
    """structlog + stdlib logging 통합 설정. main.py 시작 시 1회 호출."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
    ]

    if settings.log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # stdlib logging도 같은 처리기 사용 (uvicorn·psycopg·google-genai 로그 통합)
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """매 요청에 request_id 할당 → contextvar에 bind → 응답 헤더로 echo."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex

        # contextvar bind — 같은 요청 안의 모든 log call이 request_id 포함
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
