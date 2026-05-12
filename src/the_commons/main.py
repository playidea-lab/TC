"""FastAPI 진입점.

The Commons backend service.
- 외부엔 internal only (Phase 1, CQ를 통해서만 접근)
- 추후 Phase 2에서 public read API 개방 예정
"""

from fastapi import FastAPI

from the_commons import __version__
from the_commons.api.evidence import router as evidence_router
from the_commons.api.health import router as health_router
from the_commons.api.ingest import router as ingest_router

app = FastAPI(
    title="The Commons",
    description="ML experiment evidence library + match-maker (internal)",
    version=__version__,
)

app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(evidence_router)

# 추후 라우터 마운트 (M2+):
# from the_commons.api.recommend import router as recommend_router
# app.include_router(recommend_router)
