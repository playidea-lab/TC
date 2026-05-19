"""content_hash pcq 정본 byte-parity 테스트.

golden = pcq 실제 build_integrity_object(commit 5e86bee) 출력. TC
재구현이 cross-impl byte-for-byte 동일해야 거버넌스 게이트·corpus
export가 의미를 가진다.
"""

import json
from pathlib import Path

import pytest

from the_commons.library.content_hash import compute_integrity, verify_integrity

_GOLDEN = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "pcq_integrity_golden.json").read_text()
)


@pytest.mark.parametrize("vec", _GOLDEN["vectors"], ids=lambda v: v["name"])
def test_compute_integrity_matches_pcq_golden(vec) -> None:
    got = compute_integrity(vec["record"])
    assert got["content_hash"] == vec["expected_integrity"]["content_hash"]
    assert got["hashed_fields"] == vec["expected_integrity"]["hashed_fields"]


def test_provenance_pinned_to_canonical_commit() -> None:
    assert _GOLDEN["provenance"]["commit"] == "5e86bee"


def test_signature_and_integrity_excluded_anti_recursion() -> None:
    rec = {
        "config": {"a": 1},
        "metrics": {"m": 2},
        "attribution": {"operator": "x", "signature": "MUST-NOT-AFFECT"},
        "integrity": {"content_hash": "sha256:STALE", "hashed_fields": []},
    }
    h1 = compute_integrity(rec)["content_hash"]
    rec2 = json.loads(json.dumps(rec))
    rec2["attribution"]["signature"] = "DIFFERENT"
    rec2["integrity"]["content_hash"] = "sha256:OTHER"
    h2 = compute_integrity(rec2)["content_hash"]
    assert h1 == h2  # signature·integrity 변경은 hash에 영향 없음


def test_verify_integrity_roundtrip() -> None:
    vec = _GOLDEN["vectors"][0]
    assert verify_integrity(vec["record"], vec["expected_integrity"]["content_hash"])
    assert not verify_integrity(vec["record"], "sha256:deadbeef")


def test_custom_hashed_fields_arg_honored_pcq_signature_parity() -> None:
    # pcq build_integrity_object(payload, hashed_fields) 시그니처 패리티:
    # 커스텀 allowlist 전달 시 그 필드만 + _EXCLUDED 항상 필터.
    rec = {"config": {"a": 1}, "metrics": {"m": 2}, "integrity": {"x": 1}}
    out = compute_integrity(rec, ["metrics", "integrity", "config"])
    assert out["hashed_fields"] == ["metrics", "config"]  # integrity 제외됨


def test_verify_uses_record_declared_hashed_fields() -> None:
    # record가 비기본 allowlist로 produce된 경우에도 충실히 검증.
    rec = {
        "config": {"a": 1},
        "metrics": {"m": 2},
        "intent": {"goal": "exploration"},
    }
    custom = ["config", "metrics"]  # 기본 9개가 아닌 축소 allowlist
    ch = compute_integrity(rec, custom)["content_hash"]
    rec["integrity"] = {"content_hash": ch, "hashed_fields": custom}
    assert verify_integrity(rec, ch)  # 선언된 allowlist로 재현 성공
    # 선언 없으면 기본 allowlist → 다른 hash → 불일치
    rec_nodecl = {k: v for k, v in rec.items() if k != "integrity"}
    assert not verify_integrity(rec_nodecl, ch)


def test_indent2_is_load_bearing() -> None:
    # indent=2 누락 시(=compact) 정본과 달라짐을 음성 확인 — 회귀 방지.
    import hashlib

    from the_commons.library.content_hash import (
        _INTEGRITY_HASHED_FIELDS,
        _resolve_dotted_path,
    )

    rec = _GOLDEN["vectors"][0]["record"]
    subset = {p: _resolve_dotted_path(rec, p) for p in _INTEGRITY_HASHED_FIELDS}
    compact = json.dumps(subset, separators=(",", ":"), sort_keys=True, default=str)
    compact_hash = "sha256:" + hashlib.sha256(compact.encode()).hexdigest()
    assert compact_hash != _GOLDEN["vectors"][0]["expected_integrity"]["content_hash"]
    assert compute_integrity(rec)["content_hash"] == (
        _GOLDEN["vectors"][0]["expected_integrity"]["content_hash"]
    )
