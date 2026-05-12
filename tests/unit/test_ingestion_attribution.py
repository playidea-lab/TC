"""attribution 검증 단위 테스트."""

import pytest

from the_commons.ingestion.attribution_validator import (
    AttributionError,
    validate_attribution,
)
from the_commons.library.content_hash import compute_content_hash


def _record(**overrides) -> dict:
    """공통 fixture — 검증 통과 가능한 minimal record."""
    base = {
        "evidence_id": "ev-test",
        "tier": "real",
        "outreach_origin": "external",
        "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "config": {"lr": 0.01},
        "metrics": {"AUC": 0.847},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {
            "contributor_id": None,
            "content_hash": "",
            "created_at": "2026-05-13T07:00:00Z",
            "pcq_version": "2.0.0",
        },
        "synthetic_source": None,
    }
    base.update(overrides)
    # content_hash 채우기 (override 후)
    base["attribution"]["content_hash"] = compute_content_hash(base)
    return base


def test_validate_passes_well_formed_real_record() -> None:
    """올바른 real record는 예외 없이 통과."""
    validate_attribution(_record())


def test_validate_rejects_missing_evidence_id() -> None:
    """evidence_id 누락 거부."""
    rec = _record()
    rec["evidence_id"] = "no-prefix"
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    with pytest.raises(AttributionError, match="evidence_id"):
        validate_attribution(rec)


def test_validate_rejects_synthetic_without_source() -> None:
    """tier=synthetic인데 synthetic_source 없으면 거부."""
    rec = _record(tier="synthetic", synthetic_source=None)
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    with pytest.raises(AttributionError, match="synthetic_source"):
        validate_attribution(rec)


def test_validate_rejects_synthetic_with_missing_subfield() -> None:
    """synthetic_source 안의 필수 subfield 누락 거부."""
    rec = _record(
        tier="synthetic",
        synthetic_source={
            "source_model": "gemini-flash-2.5",
            # prompt_hash 누락
            "generated_at": "2026-05-13T06:00:00Z",
        },
    )
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    with pytest.raises(AttributionError, match="prompt_hash"):
        validate_attribution(rec)


def test_validate_rejects_real_with_synthetic_source() -> None:
    """tier=real인데 synthetic_source 채워있으면 일관성 위반."""
    rec = _record(
        synthetic_source={
            "source_model": "x",
            "prompt_hash": "y",
            "generated_at": "2026-05-13T06:00:00Z",
        },
    )
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    with pytest.raises(AttributionError, match="일관성"):
        validate_attribution(rec)


def test_validate_rejects_unsupported_pcq_version() -> None:
    """pcq major 2.x만 지원."""
    rec = _record()
    rec["attribution"]["pcq_version"] = "1.5.0"
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    with pytest.raises(AttributionError, match="pcq"):
        validate_attribution(rec)


def test_validate_rejects_content_hash_mismatch() -> None:
    """declared content_hash가 실제 hash와 다르면 거부 — 변조 감지."""
    rec = _record()
    rec["attribution"]["content_hash"] = "sha256:0" * 64
    with pytest.raises(AttributionError, match="content_hash 불일치"):
        validate_attribution(rec)


def test_validate_rejects_unknown_tier() -> None:
    """tier='maybe' 같은 알 수 없는 값 거부."""
    rec = _record(tier="maybe")
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    with pytest.raises(AttributionError, match="tier"):
        validate_attribution(rec)
