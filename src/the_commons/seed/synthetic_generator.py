"""LLM 증류 synthetic evidence 생성기.

LLM에게 "이 cluster에서 어떤 recipe가 어떤 metric을 보일지" 물어 합성 evidence
record를 만든다. 모든 record는:
- tier='synthetic'
- synthetic_source attribution 강제 (source_model, prompt_hash, generated_at)
- content_hash 자동 계산
- pcq 2.x schema 준수

생성 후 /ingest로 deposit하면 cluster에 즉시 진입.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from the_commons.library.content_hash import compute_content_hash

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedSpec:
    """synthetic evidence 1건 생성에 필요한 입력."""

    modality: str
    sample_count_band: str
    intent_goal: str
    recipe_id: str
    framework: str | None = None


@dataclass(frozen=True)
class SyntheticPrediction:
    """LLM이 반환한 raw prediction — 검증 전 단계."""

    expected_metric_name: str
    expected_metric_value: float
    estimated_runtime_sec: int | None
    hyperparams: dict[str, Any]
    reasoning: str


@runtime_checkable
class SyntheticOracle(Protocol):
    """LLM 호출 추상화 — test에서 fake로 교체 가능."""

    async def predict(self, spec: SeedSpec) -> SyntheticPrediction: ...


def build_synthetic_record(
    spec: SeedSpec,
    prediction: SyntheticPrediction,
    *,
    source_model: str,
    prompt_hash: str,
    evidence_id_suffix: str,
) -> dict[str, Any]:
    """SeedSpec + LLM prediction → 완전한 pcq 2.x synthetic record.

    검증·저장은 /ingest 경로 그대로 사용.
    """
    now = datetime.now(UTC)
    record: dict[str, Any] = {
        "evidence_id": f"ev-syn-{evidence_id_suffix}",
        "tier": "synthetic",
        "outreach_origin": "internal",  # PI Lab 시드 origin
        "intent": {
            "goal": spec.intent_goal,
            "expected_baseline": {
                "metric": prediction.expected_metric_name,
                "value": prediction.expected_metric_value,
            },
            "tolerance": {"direction": "higher_is_better", "margin": 0.05},
        },
        "data_fingerprint": {
            "modality": spec.modality,
            "sample_count_band": spec.sample_count_band,
            "schema_summary": {},
            "statistical_moments": {},
        },
        "config": {
            "recipe_id": spec.recipe_id,
            "framework": spec.framework or spec.recipe_id,
            **prediction.hyperparams,
        },
        "metrics": {
            prediction.expected_metric_name: prediction.expected_metric_value,
        },
        "worker_spec": {
            "cpu_cores": 1,
            "ram_gb": 1,
            "has_gpu": False,
        },
        "attribution": {
            "contributor_id": None,
            "content_hash": "",  # 직후 채움
            "created_at": now.isoformat(),
            "pcq_version": "2.0.0",
        },
        "synthetic_source": {
            "source_model": source_model,
            "prompt_hash": prompt_hash,
            "generated_at": now.isoformat(),
            "verifier": None,
        },
    }
    record["attribution"]["content_hash"] = compute_content_hash(record)
    return record


async def generate_seed_records(
    oracle: SyntheticOracle,
    specs: list[SeedSpec],
    *,
    source_model: str,
) -> list[dict[str, Any]]:
    """N개 spec → N개 synthetic record (LLM 1회씩 호출)."""
    records: list[dict[str, Any]] = []
    for i, spec in enumerate(specs):
        try:
            prediction = await oracle.predict(spec)
        except Exception as exc:  # noqa: BLE001 — 외부 LLM 실패는 skip
            logger.warning(
                "LLM 호출 실패 spec=%s: %s — skip", spec, exc
            )
            continue
        prompt_hash = _prompt_hash(spec)
        record = build_synthetic_record(
            spec,
            prediction,
            source_model=source_model,
            prompt_hash=prompt_hash,
            evidence_id_suffix=f"{i:05d}-{prompt_hash[7:15]}",
        )
        records.append(record)
    return records


def _prompt_hash(spec: SeedSpec) -> str:
    """spec의 canonical JSON SHA256 — 재현용 prompt_hash."""
    payload = json.dumps(spec.__dict__, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
