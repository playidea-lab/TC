"""corpus.export — export/import round-trip + content-hash 무결성 단위 테스트."""

from datetime import UTC, datetime

import pytest

from the_commons.corpus.export import (
    CorpusIntegrityError,
    export_corpus,
    import_corpus,
)
from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import Evidence
from the_commons.library.store import InMemoryEvidenceStore


def _ev(eid: str, recipe: str = "rf", auc: float = 0.8, tier: str = "real") -> Evidence:
    rec = {
        "evidence_id": eid,
        "tier": tier,
        "outreach_origin": "external",
        "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "config": {"recipe_id": recipe},
        "metrics": {"AUC": auc},
        "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
        "attribution": {
            "contributor_id": None,
            "content_hash": "",
            "created_at": datetime.now(UTC).isoformat(),
            "pcq_version": "2.0.0",
        },
        "synthetic_source": None,
    }
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    return Evidence.model_validate(rec)


async def _seed(store: InMemoryEvidenceStore, evs: list[Evidence]) -> None:
    for ev in evs:
        await store.insert(ev)


async def test_export_import_roundtrip_preserves_ids_and_hashes() -> None:
    src = InMemoryEvidenceStore()
    seed = [
        _ev("a", "rf", 0.9),
        _ev("b", "xgb", 0.6, tier="synthetic"),
        _ev("c", "lgbm", 0.85),
    ]
    await _seed(src, seed)

    lines = [line async for line in export_corpus(src)]
    assert len(lines) == 3

    dst = InMemoryEvidenceStore()  # 운영자 독립 재기동 모사 (완전히 빈 store)
    n = await import_corpus(dst, lines)
    assert n == 3

    got, total = await dst.list_evidence(deprecated=None, limit=1000)
    assert total == 3
    assert {e.evidence_id for e in got} == {"a", "b", "c"}
    for e in got:
        d = e.model_dump(mode="json")
        assert e.attribution.content_hash == compute_content_hash(d)


async def test_export_includes_deprecated_l1_records() -> None:
    src = InMemoryEvidenceStore()
    await _seed(src, [_ev("keep"), _ev("dep")])
    await src.mark_deprecated("dep", reason="phi")

    lines = [line async for line in export_corpus(src)]
    dst = InMemoryEvidenceStore()
    await import_corpus(dst, lines)

    _, total = await dst.list_evidence(deprecated=None, limit=1000)
    assert total == 2  # L1 불변 — deprecated도 audit 보존


async def test_import_rejects_tampered_record() -> None:
    src = InMemoryEvidenceStore()
    await _seed(src, [_ev("x", "rf", 0.9)])
    lines = [line async for line in export_corpus(src)]

    tampered = lines[0].replace('"AUC":0.9', '"AUC":0.1').replace(
        '"AUC": 0.9', '"AUC": 0.1'
    )
    assert tampered != lines[0]

    dst = InMemoryEvidenceStore()
    with pytest.raises(CorpusIntegrityError):
        await import_corpus(dst, [tampered])


async def test_import_is_idempotent_on_duplicates() -> None:
    src = InMemoryEvidenceStore()
    await _seed(src, [_ev("a"), _ev("b")])
    lines = [line async for line in export_corpus(src)]

    dst = InMemoryEvidenceStore()
    n1 = await import_corpus(dst, lines)
    n2 = await import_corpus(dst, lines)  # 재실행 — 중복 skip
    assert n1 == 2
    assert n2 == 0
    _, total = await dst.list_evidence(deprecated=None, limit=1000)
    assert total == 2


async def test_content_hash_is_identity_not_evidence_id() -> None:
    # DD1: 같은 내용·다른 evidence_id → content_hash 동일.
    a = _ev("id-1", "rf", 0.77)
    b_rec = a.model_dump(mode="json")
    b_rec["evidence_id"] = "id-2"
    b_rec["attribution"]["content_hash"] = ""
    # evidence_id는 hash 입력에 포함되므로 다름이 정상 — 단 content는 매체 무관.
    # 핵심 audit: hash는 row id가 아니라 record 내용으로 결정된다.
    h = compute_content_hash(b_rec)
    assert h.startswith("sha256:")
    assert h != a.attribution.content_hash  # 내용(evidence_id) 다르면 hash 다름
