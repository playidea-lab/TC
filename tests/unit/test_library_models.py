"""evidence Pydantic 모델 — schema·constraint 검증."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from the_commons.library.models import (
    DataFingerprint,
    Evidence,
    Intent,
    PcqRecord,
    SyntheticSource,
    WorkerSpec,
)


def _minimal_evidence_kwargs() -> dict:
    """필수 필드만 채운 envelope evidence kwargs."""
    return {
        "evidence_id": "ev-test",
        "tier": "real",
        "outreach_origin": "external",
        "pcq_record": PcqRecord(
            intent=Intent(goal="exploration"),
            data_fingerprint=DataFingerprint(
                modality="tabular", sample_count_band="10k-100k"
            ),
            config={"lr": 0.01},
            metrics={"AUC": 0.847},
            worker_spec=WorkerSpec(cpu_cores=32, ram_gb=64, has_gpu=True),
            contract_version="2.0",
        ),
    }


def test_minimal_real_evidence_parses() -> None:
    """필수 필드만 있는 real evidence가 파싱돼야 한다."""
    ev = Evidence(**_minimal_evidence_kwargs())
    assert ev.tier == "real"
    assert ev.synthetic_source is None


def test_intent_rejects_unknown_goal() -> None:
    """intent.goal은 정의된 enum만 허용."""
    with pytest.raises(ValidationError):
        Intent(goal="something_random")  # type: ignore[arg-type]


def test_intent_allows_null_baseline_and_tolerance() -> None:
    """expected_baseline·tolerance는 null 허용."""
    intent = Intent(goal="exploration", expected_baseline=None, tolerance=None)
    assert intent.expected_baseline is None
    assert intent.tolerance is None


def test_intent_preserves_extra_fields_extra_allow() -> None:
    """v4.10.0: Intent extra='allow' — 미지 필드 보존 (R6 additive 본질).

    이전 forbid 의미론은 pcq 미래 cycle마다 TC sync 사이클을 강제했음.
    extra='allow' 전환으로 unhashed 미지 필드는 __pydantic_extra__에 보존되어
    model_dump 재직렬화 시 byte-parity 유지 → content_hash mirror 정합 전제.
    """
    intent = Intent(goal="exploration", weird_field="future")  # type: ignore[call-arg]
    assert intent.goal == "exploration"
    assert intent.model_extra == {"weird_field": "future"}


def test_synthetic_source_required_fields() -> None:
    """tier=synthetic 시 사용하는 attribution — 필수 필드 누락 거부."""
    with pytest.raises(ValidationError):
        SyntheticSource(source_model="x")  # type: ignore[call-arg]


def test_synthetic_evidence_parses_with_source() -> None:
    """synthetic_source가 있으면 tier=synthetic 파싱 OK."""
    kwargs = _minimal_evidence_kwargs()
    kwargs["tier"] = "synthetic"
    kwargs["synthetic_source"] = SyntheticSource(
        source_model="gemini-flash-2.5",
        prompt_hash="sha256:xyz",
        generated_at=datetime.now(UTC),
    )
    ev = Evidence(**kwargs)
    assert ev.tier == "synthetic"
    assert ev.synthetic_source is not None
    assert ev.synthetic_source.source_model == "gemini-flash-2.5"


def test_worker_spec_rejects_zero_cores() -> None:
    """cpu_cores >= 1, ram_gb >= 1 강제."""
    with pytest.raises(ValidationError):
        WorkerSpec(cpu_cores=0, ram_gb=64)


def test_outreach_origin_only_accepts_known_values() -> None:
    """outreach_origin = internal | external 만."""
    kwargs = _minimal_evidence_kwargs()
    kwargs["outreach_origin"] = "spam"
    with pytest.raises(ValidationError):
        Evidence(**kwargs)


def test_evidence_deprecated_defaults_false() -> None:
    """ingestion 시점엔 deprecated=False가 기본."""
    ev = Evidence(**_minimal_evidence_kwargs())
    assert ev.deprecated is False
    assert ev.deprecated_at is None
