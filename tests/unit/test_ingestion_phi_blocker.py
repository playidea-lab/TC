"""PHI 차단·quantize 단위 테스트."""

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


def test_block_phi_passes_clean_record() -> None:
    """PHI 없는 record는 위반 없이 통과."""
    record = {
        "evidence_id": "ev-1",
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count_band": "10k-100k",
        },
        "config": {"lr": 0.01},
    }
    cleaned = block_phi(record)
    assert cleaned["data_fingerprint"]["sample_count_band"] == "10k-100k"


def test_block_phi_rejects_raw_samples_field() -> None:
    """data_fingerprint에 raw_samples가 있으면 거부."""
    record = {
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count_band": "1k-10k",
            "raw_samples": [["row1"], ["row2"]],
        }
    }
    with pytest.raises(PHIViolationError):
        block_phi(record)


def test_block_phi_rejects_patient_id() -> None:
    """어디든 patient_id가 있으면 거부 (nested 포함)."""
    record = {
        "data_fingerprint": {
            "modality": "vision",
            "sample_count_band": "100-1k",
            "metadata": {"patient_id": "p-001"},
        }
    }
    with pytest.raises(PHIViolationError):
        block_phi(record)


def test_block_phi_rejects_email_anywhere() -> None:
    """email 키는 어느 nested level에서도 거부."""
    record = {
        "attribution": {"contributor_id": "x", "email": "leaked@x.com"},
    }
    with pytest.raises(PHIViolationError) as exc_info:
        block_phi(record)
    assert "email" in str(exc_info.value)


def test_block_phi_auto_quantizes_exact_sample_count() -> None:
    """정확한 sample_count는 silent quantize → 대역 라벨로 변환."""
    record = {
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count": 12_847,  # 정확한 N
        }
    }
    cleaned = block_phi(record)
    assert "sample_count" not in cleaned["data_fingerprint"]
    assert cleaned["data_fingerprint"]["sample_count_band"] == "10k-100k"


def test_block_phi_violation_message_lists_paths() -> None:
    """위반 message에 path가 포함되어 디버깅 가능."""
    record = {
        "data_fingerprint": {
            "raw_samples": [],
            "patient_id": "x",
        }
    }
    with pytest.raises(PHIViolationError) as exc_info:
        block_phi(record)
    msg = str(exc_info.value)
    assert "$.data_fingerprint.raw_samples" in msg
    assert "$.data_fingerprint.patient_id" in msg


def test_block_phi_with_list_nesting_finds_violation() -> None:
    """list 안의 dict에 있는 위반도 감지."""
    record = {
        "validation_report": {
            "samples": [{"phone": "010-..."}, {"ok": True}],
        }
    }
    with pytest.raises(PHIViolationError):
        block_phi(record)


def test_block_phi_does_not_mutate_input() -> None:
    """입력 record는 변경되지 않아야 한다 (얕은 사본 반환)."""
    record = {
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count": 5_000,
        }
    }
    _ = block_phi(record)
    # 원본은 그대로
    assert record["data_fingerprint"]["sample_count"] == 5_000
