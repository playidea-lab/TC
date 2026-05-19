"""attribution / integrity 검증 단위 테스트 (envelope 정합)."""

import pytest

from the_commons.ingestion.attribution_validator import (
    AttributionError,
    validate_attribution,
)
from the_commons.library.content_hash import compute_integrity


def _record(**envelope_overrides) -> dict:
    """envelope 형태로 검증 통과 가능한 minimal record. integrity 자동 stamp."""
    pcq = {
        "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "config": {"lr": 0.01},
        "metrics": {"AUC": 0.847},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {"operator": None},
        "contract_version": "2.0",
    }
    pcq_overrides = envelope_overrides.pop("pcq", {})
    pcq.update(pcq_overrides)
    base = {
        "evidence_id": "ev-test",
        "tier": "real",
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": pcq,
    }
    base.update(envelope_overrides)
    # ingest의 1.5단계와 동일 — integrity server-derive
    base["pcq_record"]["integrity"] = compute_integrity(base["pcq_record"])
    return base


def test_validate_passes_well_formed_real_record() -> None:
    validate_attribution(_record())


def test_validate_rejects_missing_evidence_id() -> None:
    rec = _record()
    rec["evidence_id"] = "no-prefix"
    with pytest.raises(AttributionError, match="evidence_id"):
        validate_attribution(rec)


@pytest.mark.parametrize(
    "bad_id",
    [
        "ev-with/slash",
        "ev-with space",
        "ev-with.dot",
        "ev-한글",
        "ev-",
    ],
)
def test_validate_rejects_invalid_evidence_id_pattern(bad_id: str) -> None:
    rec = _record()
    rec["evidence_id"] = bad_id
    with pytest.raises(AttributionError, match="evidence_id"):
        validate_attribution(rec)


def test_validate_rejects_overlong_evidence_id() -> None:
    rec = _record()
    rec["evidence_id"] = "ev-" + "a" * 200
    with pytest.raises(AttributionError, match="evidence_id"):
        validate_attribution(rec)


def test_validate_rejects_synthetic_without_source() -> None:
    rec = _record(tier="synthetic", synthetic_source=None)
    with pytest.raises(AttributionError, match="synthetic_source"):
        validate_attribution(rec)


def test_validate_rejects_synthetic_with_missing_subfield() -> None:
    rec = _record(
        tier="synthetic",
        synthetic_source={
            "source_model": "gemini-flash-2.5",
            "generated_at": "2026-05-13T06:00:00Z",
        },
    )
    with pytest.raises(AttributionError, match="prompt_hash"):
        validate_attribution(rec)


def test_validate_rejects_real_with_synthetic_source() -> None:
    rec = _record(
        synthetic_source={
            "source_model": "x",
            "prompt_hash": "y",
            "generated_at": "2026-05-13T06:00:00Z",
        },
    )
    with pytest.raises(AttributionError, match="일관성"):
        validate_attribution(rec)


def test_validate_rejects_unsupported_contract_version() -> None:
    """pcq 2.x | 1.x만 지원 (R6 additive). 그 외는 거부."""
    rec = _record(pcq={"contract_version": "3.5"})
    rec["pcq_record"]["integrity"] = compute_integrity(rec["pcq_record"])
    with pytest.raises(AttributionError, match="contract_version"):
        validate_attribution(rec)


def test_validate_accepts_absent_contract_version_as_1x() -> None:
    """contract_version 부재 = 1.x (R6 additive). valid 허용."""
    rec = _record()
    rec["pcq_record"].pop("contract_version", None)
    rec["pcq_record"]["integrity"] = compute_integrity(rec["pcq_record"])
    validate_attribution(rec)  # 예외 없음


def test_validate_rejects_content_hash_mismatch() -> None:
    """변조된 integrity content_hash는 거부."""
    rec = _record()
    rec["pcq_record"]["integrity"]["content_hash"] = "sha256:" + "0" * 64
    with pytest.raises(AttributionError, match="content_hash 불일치"):
        validate_attribution(rec)


def test_validate_rejects_unknown_tier() -> None:
    rec = _record(tier="maybe")
    with pytest.raises(AttributionError, match="tier"):
        validate_attribution(rec)
