"""PHI 차단·quantize 단위 테스트 (envelope 정합)."""

import pytest

from the_commons.ingestion.phi_blocker import (
    PHIViolationError,
    block_phi,
    quantize_sample_count,
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "0-100"),
        (50, "0-100"),
        (100, "100-1k"),
        (999, "100-1k"),
        (1_000, "1k-10k"),
        (50_000, "10k-100k"),
        (200_000, "100k-1M"),
        (5_000_000, "1M-10M"),
        (20_000_000, "10M+"),
        (-1, "0-100"),
    ],
)
def test_quantize_sample_count_maps_to_band(count: int, expected: str) -> None:
    """sample count는 정해진 대역 라벨로 매핑."""
    assert quantize_sample_count(count) == expected


def _env(**pcq_fields) -> dict:
    """envelope 셸 — pcq_record에 주어진 필드 주입."""
    return {"evidence_id": "ev-1", "tier": "real", "outreach_origin": "external",
            "pcq_record": dict(pcq_fields)}


def test_block_phi_passes_clean_record() -> None:
    record = _env(
        data_fingerprint={"modality": "tabular", "sample_count_band": "10k-100k"},
        config={"lr": 0.01},
    )
    cleaned = block_phi(record)
    assert cleaned["pcq_record"]["data_fingerprint"]["sample_count_band"] == "10k-100k"


def test_block_phi_rejects_raw_samples_field() -> None:
    record = _env(data_fingerprint={
        "modality": "tabular", "sample_count_band": "1k-10k",
        "raw_samples": [["row1"], ["row2"]],
    })
    with pytest.raises(PHIViolationError):
        block_phi(record)


def test_block_phi_rejects_patient_id() -> None:
    record = _env(data_fingerprint={
        "modality": "vision", "sample_count_band": "100-1k",
        "metadata": {"patient_id": "p-001"},
    })
    with pytest.raises(PHIViolationError):
        block_phi(record)


def test_block_phi_rejects_email_anywhere() -> None:
    """email 키는 어느 nested level에서도 거부 (envelope 외부 포함)."""
    record = _env(attribution={"operator": "x", "email": "leaked@x.com"})
    with pytest.raises(PHIViolationError) as exc_info:
        block_phi(record)
    assert "email" in str(exc_info.value)


def test_block_phi_auto_quantizes_exact_sample_count() -> None:
    record = _env(data_fingerprint={
        "modality": "tabular", "sample_count": 12_847,
    })
    cleaned = block_phi(record)
    fp = cleaned["pcq_record"]["data_fingerprint"]
    assert "sample_count" not in fp
    assert fp["sample_count_band"] == "10k-100k"


def test_block_phi_violation_message_lists_paths() -> None:
    record = _env(data_fingerprint={"raw_samples": [], "patient_id": "x"})
    with pytest.raises(PHIViolationError) as exc_info:
        block_phi(record)
    msg = str(exc_info.value)
    assert "raw_samples" in msg
    assert "patient_id" in msg


def test_block_phi_with_list_nesting_finds_violation() -> None:
    record = _env(validation_report={"samples": [{"phone": "010-..."}, {"ok": True}]})
    with pytest.raises(PHIViolationError):
        block_phi(record)


def test_block_phi_does_not_mutate_input() -> None:
    record = _env(data_fingerprint={"modality": "tabular", "sample_count": 5_000})
    _ = block_phi(record)
    assert record["pcq_record"]["data_fingerprint"]["sample_count"] == 5_000
