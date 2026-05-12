"""Health check 엔드포인트. liveness + version 정보."""

from fastapi import APIRouter
from pydantic import BaseModel

from the_commons import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health 응답 schema."""

    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """서비스가 응답 가능한지 확인하는 엔드포인트."""
    return HealthResponse(status="ok", version=__version__)
