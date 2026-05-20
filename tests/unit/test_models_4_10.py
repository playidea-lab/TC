"""pcq v4.10.0 Reproducibility Pack model 회귀 — Code/Scope/DataRef + extra='allow'."""

import pytest
from pydantic import ValidationError

from the_commons.library.models import (
    Code,
    DataRef,
    Intent,
    PcqRecord,
    Scope,
)

# ---- Code / Scope -----------------------------------------------------------


def test_code_minimal_entry_script() -> None:
    code = Code.model_validate(
        {"content_sha256": "abc123", "scope": {"kind": "entry_script"}}
    )
    assert code.content_sha256 == "abc123"
    assert code.scope.kind == "entry_script"
    assert code.scope.files is None
    assert code.scope.root is None


def test_code_file_list_with_files() -> None:
    code = Code.model_validate(
        {
            "content_sha256": "def456",
            "scope": {"kind": "file_list", "files": ["a.py", "b.py"]},
        }
    )
    assert code.scope.kind == "file_list"
    assert code.scope.files == ["a.py", "b.py"]


def test_code_repo_subset_with_root() -> None:
    code = Code.model_validate(
        {
            "content_sha256": "789abc",
            "scope": {"kind": "repo_subset", "root": "src/", "files": ["m.py"]},
        }
    )
    assert code.scope.kind == "repo_subset"
    assert code.scope.root == "src/"


def test_scope_kind_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        Scope.model_validate({"kind": "invalid_kind"})


def test_code_requires_scope() -> None:
    """code present 시 scope required (pcq schema NORMATIVE)."""
    with pytest.raises(ValidationError):
        Code.model_validate({"content_sha256": "abc"})  # scope 누락


def test_code_requires_scope_kind() -> None:
    """code present 시 scope.kind required."""
    with pytest.raises(ValidationError):
        Code.model_validate({"content_sha256": "abc", "scope": {}})  # kind 누락


# ---- DataRef ----------------------------------------------------------------


def test_data_ref_minimal() -> None:
    dr = DataRef.model_validate({"uri": "s3://bucket/data.parquet"})
    assert dr.uri == "s3://bucket/data.parquet"
    assert dr.content_sha256 is None  # PHI dual-gate 호환
    assert dr.size_bytes is None


def test_data_ref_full() -> None:
    dr = DataRef.model_validate(
        {
            "uri": "s3://b/d.parquet",
            "content_sha256": "deadbeef",
            "size_bytes": 1024,
        }
    )
    assert dr.content_sha256 == "deadbeef"
    assert dr.size_bytes == 1024


def test_data_ref_phi_stripped_content_sha256_none() -> None:
    """PHI 도메인: content_sha256 명시적 None 허용 (BL-4 dual gate)."""
    dr = DataRef.model_validate({"uri": "phi://patient/db", "content_sha256": None})
    assert dr.content_sha256 is None


def test_data_ref_negative_size_rejected() -> None:
    with pytest.raises(ValidationError):
        DataRef.model_validate({"uri": "s3://x", "size_bytes": -1})


# ---- PcqRecord 3 신규 필드 --------------------------------------------------


def _minimal_record_kwargs() -> dict:
    return {"contract_version": "2.0"}


def test_pcq_record_all_3_new_fields_absent() -> None:
    """R6 additive: 신규 3 필드 모두 absent도 valid (pre-4.10 record)."""
    rec = PcqRecord.model_validate(_minimal_record_kwargs())
    assert rec.code is None
    assert rec.seeds is None
    assert rec.data_ref is None


def test_pcq_record_with_code() -> None:
    rec = PcqRecord.model_validate(
        {
            **_minimal_record_kwargs(),
            "code": {"content_sha256": "abc", "scope": {"kind": "entry_script"}},
        }
    )
    assert rec.code is not None
    assert rec.code.scope.kind == "entry_script"


def test_pcq_record_with_seeds_multi() -> None:
    rec = PcqRecord.model_validate(
        {**_minimal_record_kwargs(), "seeds": {"main": 42, "data": "rng-A"}}
    )
    assert rec.seeds == {"main": 42, "data": "rng-A"}


def test_pcq_record_with_data_ref() -> None:
    rec = PcqRecord.model_validate(
        {
            **_minimal_record_kwargs(),
            "data_ref": {"uri": "s3://b/d", "content_sha256": "deadbeef"},
        }
    )
    assert rec.data_ref is not None
    assert rec.data_ref.uri == "s3://b/d"


def test_pcq_record_all_3_new_fields_present() -> None:
    rec = PcqRecord.model_validate(
        {
            **_minimal_record_kwargs(),
            "code": {"content_sha256": "abc", "scope": {"kind": "entry_script"}},
            "seeds": {"main": 42},
            "data_ref": {"uri": "s3://b/d"},
        }
    )
    assert rec.code is not None
    assert rec.seeds is not None
    assert rec.data_ref is not None


# ---- extra='allow' R6 additive 본질 보존 -----------------------------------


def test_intent_extra_allow_preserves_unknown_field() -> None:
    """Intent에 미지 필드 → __pydantic_extra__에 보존."""
    intent = Intent.model_validate(
        {"goal": "exploration", "future_field_xyz": {"some": "data"}}
    )
    assert intent.model_extra is not None
    assert intent.model_extra["future_field_xyz"] == {"some": "data"}


def test_pcq_record_extra_allow_preserves_unknown_top_level() -> None:
    """PcqRecord에 미지 top-level 필드 → __pydantic_extra__ 보존."""
    rec = PcqRecord.model_validate(
        {**_minimal_record_kwargs(), "future_attestation": {"tee_quote": "xyz"}}
    )
    assert rec.model_extra is not None
    assert rec.model_extra["future_attestation"] == {"tee_quote": "xyz"}


def test_pcq_record_model_dump_round_trip_byte_parity() -> None:
    """model_dump 후 재구성 시 미지 필드 보존 — content_hash mirror 정합 전제."""
    payload = {
        **_minimal_record_kwargs(),
        "code": {"content_sha256": "abc", "scope": {"kind": "entry_script"}},
        "seeds": {"main": 42},
        "data_ref": {"uri": "s3://b/d", "content_sha256": "deadbeef"},
        "future_unknown": {"k": "v"},
    }
    rec = PcqRecord.model_validate(payload)
    dumped = rec.model_dump(exclude_none=True)
    assert dumped["future_unknown"] == {"k": "v"}
    assert dumped["code"]["scope"]["kind"] == "entry_script"
    assert dumped["seeds"] == {"main": 42}
    assert dumped["data_ref"]["content_sha256"] == "deadbeef"
