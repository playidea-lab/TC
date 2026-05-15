"""Health endpoints — liveness(/health) + readiness(/ready).

K8s liveness probe는 process가 살아있는지만 확인 (DB·외부 API 무관).
readiness probe는 *요청을 받을 준비*인지 — DB connection 가능해야 OK.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from the_commons import __version__
from the_commons.db.session import get_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Liveness 응답 schema."""

    status: str
    version: str


class ReadyResponse(BaseModel):
    """Readiness 응답 schema — 외부 의존성 검증 결과 포함."""

    status: str
    version: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """liveness probe — process 살아있음만 확인. 외부 의존성 무관.

    K8s에서 이 endpoint 실패 = pod 재시작 트리거이므로 정말 *process down*만
    감지해야 한다. DB·Gemini 일시 장애로 재시작 트리거되면 안 됨.
    """
    return HealthResponse(status="ok", version=__version__)


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"description": "service is not ready to accept traffic"}},
)
async def ready() -> ReadyResponse:
    """readiness probe — DB connection 가능해야 OK.

    실패 시 503. K8s에서 traffic 라우팅을 끄지만 pod는 살려둠. DB가 다시
    살아나면 traffic 받기 재개.
    """
    checks: dict[str, str] = {}

    try:
        async with get_connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — readiness fallback
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"reason": "database unreachable", "error": str(exc)},
        ) from exc

    return ReadyResponse(status="ready", version=__version__, checks=checks)
