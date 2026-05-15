"""FastAPI 진입점.

The Commons backend service.
- 외부엔 internal only (Phase 1, CQ를 통해서만 접근)
- 추후 Phase 2에서 public read API 개방 예정
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from the_commons import __version__
from the_commons.api.evidence import router as evidence_router
from the_commons.api.health import router as health_router
from the_commons.api.ingest import router as ingest_router
from the_commons.api.recommend import router as recommend_router
from the_commons.api.verdict import router as verdict_router
from the_commons.db.session import close_pool
from the_commons.logging_config import RequestIDMiddleware, configure_logging

# structured logging + request_id 활성화 (settings.log_format 기준)
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """startup/shutdown lifecycle.

    pool은 lazy-init (`init_pool`은 첫 요청에서). shutdown 시에만 명시 close
    — graceful shutdown 시 in-flight 쿼리가 끝난 후 connection 정리.
    """
    logger.info("the-commons starting (version=%s)", __version__)
    try:
        yield
    finally:
        logger.info("the-commons shutting down — closing DB pool")
        await close_pool()


app = FastAPI(
    title="The Commons",
    description="ML experiment evidence library + match-maker (internal)",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)

app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(evidence_router)
app.include_router(recommend_router)
app.include_router(verdict_router)
