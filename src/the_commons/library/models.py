"""TC Evidence models — pcq 2.x envelope (R9/R10/R12, vendored 정본).

R9: Evidence는 pcq run_record를 감싸는 envelope.
  Evelope-owned (TC scope, R10): evidence_id, tier, outreach_origin,
    synthetic_source, deprecated 등 L3 visibility.
  pcq_record: pcq 2.x run_record verbatim (intent/config/metrics/data_fingerprint/
    worker_spec/attribution(WHO)/integrity/contract_version 등).

R6 additive: 1.x record(intent/integrity/contract_version 부재)도 valid —
모든 pcq 2.x 신규 필드는 Optional + default None.

R12 매핑(NORMATIVE):
  - attribution.contributor_id → pcq attribution.operator
  - attribution.created_at      → run_record timestamp (last_updated_at 등)
  - attribution.pcq_version     → top-level contract_version
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# TC envelope-only enums (R10 — pcq 2.x 필드 아님)
Tier = Literal["real", "synthetic"]
Outreach = Literal["internal", "external"]

IntentGoal = Literal[
    "baseline_reproduction",
    "sota_challenge",
    "ablation",
    "hyperparam_sweep",
    "exploration",
]


# ----------------------------------------------------------------------------
# pcq_record 내부 — pcq 2.x 정본 형태
# ----------------------------------------------------------------------------


class Intent(BaseModel):
    """pcq 2.x intent — 전 필드 null 허용 (정본 §2.x).

    R6 additive 본질 받기 위해 extra='allow' (pcq 미래 cycle의 unhashed 필드 보존).
    """

    model_config = ConfigDict(extra="allow")

    goal: IntentGoal | None = None
    expected_baseline: dict[str, Any] | None = Field(
        default=None, description="예: {'metric': 'AUC', 'value': 0.84}"
    )
    tolerance: dict[str, Any] | None = Field(
        default=None, description="예: {'direction': 'higher_is_better', 'margin': 0.02}"
    )


class DataFingerprint(BaseModel):
    """pcq 2.x data_fingerprint — PHI 도메인은 hints-only(정본 §PHI)."""

    model_config = ConfigDict(extra="allow")

    modality: str = Field(description="tabular/vision/nlp/...")
    sample_count_band: str = Field(
        description="'1k-10k', '10k-100k' 등 대역. PHI 도메인은 정확값 금지."
    )
    schema_summary: dict[str, Any] = Field(default_factory=dict)
    statistical_moments: dict[str, Any] = Field(default_factory=dict)


class WorkerSpec(BaseModel):
    """pcq 2.x worker_spec — 하드웨어 사양(PHI 아님)."""

    model_config = ConfigDict(extra="allow")

    cpu_cores: int = Field(ge=1)
    ram_gb: int = Field(ge=1)
    gpu_model: str | None = None
    vram_gb: int | None = None
    has_gpu: bool = False


class Attribution(BaseModel):
    """pcq 2.x attribution = WHO (v4.4 행위자 정체성).

    무결성 해시와 *별개*다 (해시는 integrity로 이동, R9 §integrity).
    pcq spec/이 향후 필드 추가 시 깨지지 않도록 extra='allow'.
    """

    model_config = ConfigDict(extra="allow")

    author: dict[str, Any] | None = Field(
        default=None, description="예: {'id':'agent-1','kind':'agent'}"
    )
    committer: dict[str, Any] | None = Field(
        default=None, description="예: {'id':'human-1','kind':'human'}"
    )
    operator: str | None = Field(
        default=None,
        description="실행 operator 식별자. TC contributor_id가 매핑됨(R12).",
    )
    session_id: str | None = None
    signature: str | None = Field(
        default=None, description="Phase 2 예약 — integrity 계산에서 제외."
    )


CodeScopeKind = Literal["entry_script", "file_list", "repo_subset"]


class Scope(BaseModel):
    """pcq 2.x code.scope — 어떤 코드 단위가 hash되었는지의 의미.

    code present 시 scope+scope.kind required (pcq schema NORMATIVE).
    """

    model_config = ConfigDict(extra="allow")

    kind: CodeScopeKind = Field(
        description="entry_script | file_list | repo_subset — hash 의미 결정"
    )
    files: list[str] | None = Field(
        default=None, description="file_list/repo_subset 시 대상 파일 경로 목록"
    )
    root: str | None = Field(
        default=None, description="repo_subset 시 루트 디렉토리"
    )


class Code(BaseModel):
    """pcq 2.x code — 기록된 코드 단위의 content hash.

    R8: code.content_sha256은 어떤 코드가 기록되었는지만 증명. 그 코드가
    실제로 실행되어 이 출력을 만들었는지는 증명하지 않음 (인과 attestation 별도).
    """

    model_config = ConfigDict(extra="allow")

    content_sha256: str = Field(description="sha256 hex of code scope content")
    scope: Scope = Field(description="hash 의미를 주는 scope (kind required)")


class DataRef(BaseModel):
    """pcq 2.x data_ref — 데이터셋 참조 (URI + 무결성).

    PHI 도메인: content_sha256이 ingest 시 stripped(None) 될 수 있음.
    Hash mirror에서 absent와 동일 동작 (BL-4 dual gate).
    """

    model_config = ConfigDict(extra="allow")

    uri: str = Field(description="데이터셋 위치 URI")
    content_sha256: str | None = Field(
        default=None,
        description="sha256 hex. PHI 도메인은 dual gate로 stripped 가능.",
    )
    size_bytes: int | None = Field(default=None, ge=0)


class Integrity(BaseModel):
    """pcq 2.x integrity — top-level content_hash·hashed_fields (정본 §integrity)."""

    model_config = ConfigDict(extra="allow")

    content_hash: str = Field(description="sha256:<hex> — build_integrity_object 산출")
    hashed_fields: list[str] = Field(
        default_factory=list,
        description="leaf-path allowlist (anti-recursion 적용)",
    )


class PcqRecord(BaseModel):
    """pcq 2.x run_record (verbatim). 전 필드 Optional — 1.x record도 valid (R6).

    pcq run_record는 status/output_dir/cmd/best/last/run_id 등 TC가 strict
    모델링하지 않는 다른 필드도 운반하므로 extra='allow'.
    """

    model_config = ConfigDict(extra="allow")

    intent: Intent | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    data_fingerprint: DataFingerprint | None = None
    worker_spec: WorkerSpec | None = None
    attribution: Attribution | None = None
    integrity: Integrity | None = None
    contract_version: str | None = None

    # pcq v4.10.0 Reproducibility Pack (R6 additive)
    code: Code | None = Field(
        default=None,
        description="기록된 코드 단위의 content hash + scope (R8 한계: 코드 기록 ≠ 실행 증명)",
    )
    seeds: dict[str, int | str] | None = Field(
        default=None,
        description="multi-seed 매핑 (예: {'main': 42, 'data': 'rng-A'})",
    )
    data_ref: DataRef | None = Field(
        default=None,
        description="데이터셋 참조 (PHI 도메인 content_sha256 stripping 가능)",
    )

    @model_validator(mode="after")
    def _validate_code_scope(self) -> "PcqRecord":
        # code present 시 scope.kind는 Pydantic이 이미 강제 (Literal).
        # 추가 invariant 없음 — pcq schema가 enforce.
        return self


# ----------------------------------------------------------------------------
# TC envelope (R9·R10) — pcq 2.x 필드 아닌 TC 소유
# ----------------------------------------------------------------------------


class SyntheticSource(BaseModel):
    """TC synthetic 전용 — pcq 2.x에 없음 (R10). tier='synthetic' 시 부착."""

    model_config = ConfigDict(extra="forbid")

    source_model: str
    prompt_hash: str
    generated_at: datetime
    verifier: str | None = Field(
        default=None, description="real evidence_id — server-derived"
    )


LineageEdgeType = Literal[
    "derives_from", "reproduces", "contradicts", "compared_to"
]


class LineageEdge(BaseModel):
    """L2 append-only lineage 엣지 — evidence 간 관계 (R10: TC envelope 소유).

    forward-compat 슬롯: matchmaker는 v0.1엔 안 읽음(저장만). v0.2에서
    정보이득 reranker가 입력 추가.
    """

    model_config = ConfigDict(extra="forbid")

    type: LineageEdgeType
    target_evidence_id: str
    metadata: dict[str, Any] | None = None


class Evidence(BaseModel):
    """TC Evidence envelope — pcq run_record를 감싸는 R9 wrapper.

    Boundary (R10): evidence_id/tier/outreach_origin/synthetic_source/lineage =
    TC envelope 전용. 그 외는 pcq_record 안.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    tier: Tier
    outreach_origin: Outreach
    synthetic_source: SyntheticSource | None = None
    lineage: list[LineageEdge] | None = Field(
        default=None,
        description="L2 lineage 엣지 (R10 TC 소유, forward-compat — v0.1 매치메이커는 미사용)",
    )

    pcq_record: PcqRecord = Field(
        default_factory=PcqRecord,
        description="pcq 2.x run_record (R6: 1.x record는 신규 필드 부재 — valid)",
    )

    # L3 visibility — DB column, ingestion 시점엔 항상 False
    deprecated: bool = False
    deprecated_reason: str | None = None
    deprecated_at: datetime | None = None
