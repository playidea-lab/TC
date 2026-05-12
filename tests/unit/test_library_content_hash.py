"""content_hash 계산·검증의 결정성·민감성 단위 테스트."""

from the_commons.library.content_hash import (
    compute_content_hash,
    verify_content_hash,
)


def _sample_record() -> dict:
    """공통 fixture — minimal evidence record."""
    return {
        "evidence_id": "ev-test",
        "tier": "real",
        "outreach_origin": "external",
        "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count_band": "10k-100k",
            "schema_summary": {},
            "statistical_moments": {},
        },
        "config": {"lr": 0.01},
        "metrics": {"AUC": 0.847},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {
            "contributor_id": None,
            "content_hash": "sha256:placeholder",
            "created_at": "2026-05-13T07:00:00Z",
            "pcq_version": "2.0.0",
        },
    }


def test_compute_hash_is_deterministic() -> None:
    """같은 record는 항상 같은 hash."""
    a = _sample_record()
    b = _sample_record()
    assert compute_content_hash(a) == compute_content_hash(b)


def test_compute_hash_ignores_key_order() -> None:
    """dict key 순서가 달라도 같은 hash (canonical 직렬화)."""
    a = _sample_record()
    # Python dict 순서를 흔든 사본
    b = {k: v for k, v in reversed(list(a.items()))}
    assert compute_content_hash(a) == compute_content_hash(b)


def test_compute_hash_excludes_attribution_content_hash() -> None:
    """attribution.content_hash 필드 자체는 hash 입력에서 제외 (chicken-and-egg)."""
    a = _sample_record()
    b = _sample_record()
    b["attribution"]["content_hash"] = "sha256:differentplaceholder"
    assert compute_content_hash(a) == compute_content_hash(b)


def test_compute_hash_changes_on_any_other_field() -> None:
    """attribution.content_hash 외 모든 변경은 hash를 바꿔야 한다."""
    a = _sample_record()
    base_hash = compute_content_hash(a)

    b = _sample_record()
    b["metrics"]["AUC"] = 0.848  # 0.001 차이
    assert compute_content_hash(b) != base_hash


def test_compute_hash_returns_sha256_prefixed_hex() -> None:
    """결과는 `sha256:<64자 hex>` 형식."""
    result = compute_content_hash(_sample_record())
    assert result.startswith("sha256:")
    digest = result.split(":", 1)[1]
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_verify_with_matching_hash_returns_true() -> None:
    """attribution.content_hash가 실제 hash와 일치하면 True."""
    record = _sample_record()
    record["attribution"]["content_hash"] = compute_content_hash(record)
    assert verify_content_hash(record) is True


def test_verify_with_tampered_record_returns_false() -> None:
    """record 변조 시 verify 실패 → L1 immutability 위반 감지."""
    record = _sample_record()
    record["attribution"]["content_hash"] = compute_content_hash(record)

    # 사후 변조
    record["metrics"]["AUC"] = 0.999
    assert verify_content_hash(record) is False


def test_verify_without_content_hash_returns_false() -> None:
    """attribution.content_hash 누락 시 verify 거부."""
    record = _sample_record()
    record["attribution"].pop("content_hash", None)
    assert verify_content_hash(record) is False
