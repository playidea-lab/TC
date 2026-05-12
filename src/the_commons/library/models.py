"""evidence Pydantic models — pcq 2.x record 표현.

DB row와 1:1 매핑되지는 않는다 (DB는 run_record JSONB로 보존 + 컬럼화 일부).
ingestion·library·matchmaker 모듈이 공통으로 쓰는 *내부 표현*.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Enum 자리 — pcq 2.x spec과 정합
Tier = Literal["real", "synthetic"]
Outreach = Literal["internal", "external"]
IntentGoal = Literal[
    "baseline_reproduction",
    "sota_challenge",
    "ablation",
    "hyperparam_sweep",
    "exploration",
]


class Intent(BaseModel):
    """3필드 intent — "성공/실패"의 spec-level 정의."""

    model_config = ConfigDict(extra="forbid")

    goal: IntentGoal
    expected_baseline: dict[str, Any] | None = Field(
        default=None,
        description="예: {'metric': 'AUC', 'value': 0.84}",
    )
    tolerance: dict[str, Any] | None = Field(
        default=None,
        description="예: {'direction': 'higher_is_better', 'margin': 0.02}",
    )


class DataFingerprint(BaseModel):
    """PHI-safe by construction — 대역 표현만 허용 (정확값은 ingestion에서 차단)."""

    model_config = ConfigDict(extra="allow")

    modality: str = Field(description="tabular/vision/nlp/...")
    sample_count_band: str = Field(
        description="'1k-10k', '10k-100k' 등 대역. 정확한 N 금지",
    )
    schema_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="tabular: 컬럼 dtype 등",
    )
    statistical_moments: dict[str, Any] = Field(
        default_factory=dict,
        description="class_balance, missing_pct, mean_band, std_band 등 — 대역만",
    )


class WorkerSpec(BaseModel):
    """하드웨어 사양 — PHI 아님, 매치메이커가 적극 활용."""

    model_config = ConfigDict(extra="allow")

    cpu_cores: int = Field(ge=1)
    ram_gb: int = Field(ge=1)
    gpu_model: str | None = None
    vram_gb: int | None = None
    has_gpu: bool = False


class SyntheticSource(BaseModel):
    """tier='synthetic' 시 attribution. retire·verify에 필수."""

    model_config = ConfigDict(extra="forbid")

    source_model: str = Field(description="예: gemini-1.5-flash, claude-sonnet")
    prompt_hash: str = Field(description="prompt re-derive용 SHA256")
    generated_at: datetime
    verifier: str | None = Field(
        default=None,
        description="real evidence_id — 사용자 재현으로 채워짐",
    )


class Attribution(BaseModel):
    """누가·언제·hash. L1 immutability 검증의 기반."""

    model_config = ConfigDict(extra="forbid")

    contributor_id: str | None = Field(
        default=None,
        description="CQ identity reference (anonymous OK v0.1)",
    )
    content_hash: str = Field(description="예: sha256:abc123...")
    created_at: datetime
    pcq_version: str = Field(default="2.0.0")


class Evidence(BaseModel):
    """pcq 2.x evidence record — TC ingestion의 입력·library의 저장 단위."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    tier: Tier
    outreach_origin: Outreach

    intent: Intent
    data_fingerprint: DataFingerprint
    config: dict[str, Any]
    metrics: dict[str, Any]
    worker_spec: WorkerSpec

    manifest: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None

    attribution: Attribution
    synthetic_source: SyntheticSource | None = None

    # L3 visibility (DB column. ingestion 시점엔 항상 False)
    deprecated: bool = False
    deprecated_reason: str | None = None
    deprecated_at: datetime | None = None
