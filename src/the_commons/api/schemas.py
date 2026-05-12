"""API request/response Pydantic schemas."""

from typing import Any

from pydantic import BaseModel, Field

from the_commons.library.models import Evidence


class IngestRequest(BaseModel):
    """POST /ingest body — pcq 2.x evidence record."""

    evidence: dict[str, Any] = Field(
        description="pcq 2.x record. ingestion 파이프라인이 검증·정화 후 저장",
    )


class ClusterImpact(BaseModel):
    """ingest 응답의 cluster impact 요약."""

    promoted_synthetic_ids: list[str] = Field(default_factory=list)
    contradicted_synthetic_ids: list[str] = Field(default_factory=list)
    cluster_bucket: str | None = None


class IngestResponse(BaseModel):
    """POST /ingest 응답."""

    evidence_id: str
    tier: str
    cluster_impact: ClusterImpact


class EvidenceReadResponse(BaseModel):
    """GET /evidence/{id} 응답 — Evidence 모델 그대로 노출."""

    evidence: Evidence
