"""corpus.export — export/import round-trip + content-hash 무결성 단위 테스트."""


import pytest

from the_commons.corpus.export import (
    CorpusIntegrityError,
    export_corpus,
    import_corpus,
)
from the_commons.library.content_hash import compute_integrity
from the_commons.library.models import Evidence
from the_commons.library.store import InMemoryEvidenceStore


def _ev(eid: str, recipe: str = "rf", auc: float = 0.8, tier: str = "real") -> Evidence:
    rec = {
        "evidence_id": eid,
        "tier": tier,
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "config": {"recipe_id": recipe},
            "metrics": {"AUC": auc},
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
            "attribution": {"operator": None},
            "contract_version": "2.0",
        },
    }
    # model_validate 후 정규화된 pcq dump 위에 stamp (Pydantic defaults 일치 보장)
    ev = Evidence.model_validate(rec)
    pcq_norm = ev.pcq_record.model_dump(mode="json")
    pcq_norm["integrity"] = compute_integrity(pcq_norm)
    rec["pcq_record"] = pcq_norm
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
        pcq = e.pcq_record.model_dump(mode="json")
        assert e.pcq_record.integrity.content_hash == compute_integrity(pcq)["content_hash"]


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


async def test_pcq_integrity_is_envelope_independent() -> None:
    # pcq 2.x: integrity는 pcq_record 내용으로만 결정 — envelope의
    # evidence_id/tier/outreach_origin은 hash 입력에 무관 (R10 정합).
    a = _ev("id-1", "rf", 0.77)
    b_rec = a.model_dump(mode="json")
    b_rec["evidence_id"] = "id-2"  # envelope만 변경
    # pcq_record는 동일 → integrity content_hash 동일이 정본 거동
    h_a = a.pcq_record.integrity.content_hash
    h_b = compute_integrity(b_rec["pcq_record"])["content_hash"]
    assert h_a == h_b
    # 그러나 pcq_record 내용을 바꾸면 hash 달라짐
    b_rec["pcq_record"]["metrics"] = {"AUC": 0.99}
    h_c = compute_integrity(b_rec["pcq_record"])["content_hash"]
    assert h_c != h_a
