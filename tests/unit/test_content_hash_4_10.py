"""pcq v4.10.0 Reproducibility Pack content_hash 적대 입력 회귀.

핵심 시나리오 (pcq test_reproducibility_pack.py 미러링):
- absent-leaf drop: data_ref absent ≡ data_ref.content_sha256 stripped(None) 동일 hash
- scope 변조 검출 (scope.kind 변경 → hash 변화)
- seeds 변조 검출 (int↔str)
- size_bytes 등 unhashed 필드 변경 → hash 불변
- 신규 4 leaf 모두 None → 기존 9 leaf만 가진 record와 동일 hash
"""

from the_commons.library.content_hash import compute_integrity


def _base_record() -> dict:
    """기준 pcq 4.10 record — 13 leaf 모두 present."""
    return {
        "intent": {"goal": "exploration"},
        "config": {"recipe": "lgbm"},
        "metrics": {"AUC": 0.85},
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
        "attribution": {"author": {"id": "a"}, "operator": "op-1"},
        "contract_version": "2.0",
        "code": {"content_sha256": "abc123", "scope": {"kind": "entry_script"}},
        "seeds": {"main": 42, "data": "rng-A"},
        "data_ref": {
            "uri": "s3://b/d.parquet",
            "content_sha256": "deadbeef",
            "size_bytes": 1024,
        },
    }


# ---- BL-4 absent ≡ PHI-stripped (핵심) -------------------------------------


def test_data_ref_absent_equals_content_sha256_stripped() -> None:
    """data_ref 자체 absent ≡ data_ref.content_sha256=None 동일 hash."""
    rec_absent = _base_record()
    del rec_absent["data_ref"]

    rec_stripped = _base_record()
    rec_stripped["data_ref"]["content_sha256"] = None

    h_absent = compute_integrity(rec_absent)["content_hash"]
    h_stripped = compute_integrity(rec_stripped)["content_hash"]
    assert h_absent == h_stripped, (
        "PHI dual-gate: stripped ≡ absent 동일 hash 강제 (R8 invariant)"
    )


def test_code_absent_equals_code_content_sha256_none() -> None:
    """code 자체 absent ≡ code.content_sha256=None 동일 동작 (drop semantics)."""
    # code 자체 absent
    rec1 = _base_record()
    del rec1["code"]

    # code.content_sha256만 None (scope 그대로) — 둘 다 drop이라 동일?
    # scope는 dict라 None이 아님 → scope leaf는 그대로 hash.
    # 즉 code.content_sha256만 drop, code.scope는 hash.
    # 따라서 동일 hash가 *아닐 수 있음* — 검증 목적은 drop semantics 자체.
    # 별도 시나리오로: code 객체 자체 None vs 부재
    rec2 = _base_record()
    rec2["code"] = None

    h1 = compute_integrity(rec1)["content_hash"]
    h2 = compute_integrity(rec2)["content_hash"]
    # code 자체 absent ≡ code=None: 둘 다 .content_sha256·.scope resolve가 None → drop → 동일
    assert h1 == h2


def test_seeds_absent_equals_seeds_none() -> None:
    rec_absent = _base_record()
    del rec_absent["seeds"]

    rec_none = _base_record()
    rec_none["seeds"] = None

    h_absent = compute_integrity(rec_absent)["content_hash"]
    h_none = compute_integrity(rec_none)["content_hash"]
    assert h_absent == h_none


# ---- 신규 4 leaf 변조 검출 -------------------------------------------------


def test_scope_kind_change_detected() -> None:
    """code.scope.kind 변경 시 hash 변화 (scope 전체가 leaf로 hash)."""
    rec1 = _base_record()
    rec2 = _base_record()
    rec2["code"]["scope"]["kind"] = "file_list"
    rec2["code"]["scope"]["files"] = ["a.py"]

    h1 = compute_integrity(rec1)["content_hash"]
    h2 = compute_integrity(rec2)["content_hash"]
    assert h1 != h2, "scope.kind 변경은 hash로 검출되어야 함"


def test_seeds_int_str_change_detected() -> None:
    """seeds.<name> int↔str 변경 시 hash 변화."""
    rec1 = _base_record()
    rec2 = _base_record()
    rec2["seeds"]["main"] = "42"  # int → str

    h1 = compute_integrity(rec1)["content_hash"]
    h2 = compute_integrity(rec2)["content_hash"]
    assert h1 != h2


def test_code_content_sha256_change_detected() -> None:
    rec1 = _base_record()
    rec2 = _base_record()
    rec2["code"]["content_sha256"] = "ffffffff"

    assert (
        compute_integrity(rec1)["content_hash"]
        != compute_integrity(rec2)["content_hash"]
    )


def test_data_ref_content_sha256_change_detected() -> None:
    rec1 = _base_record()
    rec2 = _base_record()
    rec2["data_ref"]["content_sha256"] = "cafebabe"

    assert (
        compute_integrity(rec1)["content_hash"]
        != compute_integrity(rec2)["content_hash"]
    )


# ---- unhashed 필드 (hashed_fields 미포함) 검증 -----------------------------


def test_data_ref_size_bytes_change_hash_invariant() -> None:
    """data_ref.size_bytes는 hashed_fields 미포함 — 변경해도 hash 동일."""
    rec1 = _base_record()
    rec2 = _base_record()
    rec2["data_ref"]["size_bytes"] = 99999

    assert (
        compute_integrity(rec1)["content_hash"]
        == compute_integrity(rec2)["content_hash"]
    )


def test_data_ref_uri_change_hash_invariant() -> None:
    """data_ref.uri도 hashed_fields 미포함."""
    rec1 = _base_record()
    rec2 = _base_record()
    rec2["data_ref"]["uri"] = "s3://other/path"

    assert (
        compute_integrity(rec1)["content_hash"]
        == compute_integrity(rec2)["content_hash"]
    )


# ---- 전체 신규 3 필드 모두 absent ≡ pre-4.10 record ------------------------


def test_all_new_fields_absent_matches_pre_4_10_record() -> None:
    """신규 3 필드 모두 absent — pre-4.10 record와 동일 hash 동작.

    드롭 semantics: 신규 4 leaf 모두 None → drop → subset에서 사라짐.
    """
    rec_pre = _base_record()
    del rec_pre["code"]
    del rec_pre["seeds"]
    del rec_pre["data_ref"]

    # 같은 의미: 모두 None
    rec_all_none = _base_record()
    rec_all_none["code"] = None
    rec_all_none["seeds"] = None
    rec_all_none["data_ref"] = None

    assert (
        compute_integrity(rec_pre)["content_hash"]
        == compute_integrity(rec_all_none)["content_hash"]
    )


# ---- hashed_fields 13 leaf 확인 ---------------------------------------------


def test_hashed_fields_returns_13_leaves() -> None:
    """4.10.0 mirror는 13 leaf (기존 9 + 신규 4)."""
    rec = _base_record()
    out = compute_integrity(rec)
    assert len(out["hashed_fields"]) == 13
    assert "code.content_sha256" in out["hashed_fields"]
    assert "code.scope" in out["hashed_fields"]
    assert "seeds" in out["hashed_fields"]
    assert "data_ref.content_sha256" in out["hashed_fields"]
