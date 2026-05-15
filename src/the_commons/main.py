"""FastAPI 진입점.

The Commons backend service.
- 외부엔 internal only (Phase 1, CQ를 통해서만 접근)
- 추후 Phase 2에서 public read API 개방 예정
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from the_commons import __version__
from the_commons.api.evidence import router as evidence_router
from the_commons.api.health import router as health_router
from the_commons.api.ingest import router as ingest_router
from the_commons.api.metrics import router as metrics_router
from the_commons.api.recommend import router as recommend_router
from the_commons.api.verdict import router as verdict_router
from the_commons.db.session import close_pool
from the_commons.logging_config import (
    BodySizeLimitMiddleware,
    RequestIDMiddleware,
    configure_logging,
)
from the_commons.settings import settings as _settings

# structured logging + request_id 활성화 (settings.log_format 기준)
configure_logging()
logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """startup/shutdown lifecycle.

    F.11 — DATABASE_URL이 설정돼 있으면 startup에서 pool eager init.
    첫 요청 latency를 깎고 *시작 시점에* DB 도달 가능 여부를 확인 (불가하면
    init 실패 + pod 재시작). DB 없는 dev/test는 lazy로 fallback.

    shutdown 시 in-flight 쿼리 완료 후 connection 정리 — graceful drain.
    """
    from the_commons.db.session import init_pool
    from the_commons.settings import settings

    logger.info("the_commons_starting", version=__version__)

    if settings.database_url and "localhost" not in settings.database_url:
        # production-ish env (DATABASE_URL이 localhost가 아니면 eager)
        try:
            await init_pool()
            logger.info("db_pool_initialized")
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "db_pool_init_failed", error=str(exc), error_type=type(exc).__name__
            )
            # eager 실패면 부팅 중단 — K8s가 재시작
            raise

    try:
        yield
    finally:
        logger.info("the_commons_shutting_down", action="close_db_pool")
        await close_pool()


app = FastAPI(
    title="The Commons",
    description="ML experiment evidence library + match-maker (internal)",
    version=__version__,
    lifespan=lifespan,
)

# 미들웨어는 LIFO 적용 — BodySizeLimit이 *먼저* 평가되도록 RequestID 다음에 add.
app.add_middleware(RequestIDMiddleware)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=_settings.max_request_body_bytes)

app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(evidence_router)
app.include_router(recommend_router)
app.include_router(verdict_router)
app.include_router(metrics_router)
