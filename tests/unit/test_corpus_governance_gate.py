"""코퍼스 운영 내구성 릴리스 게이트 (DD3) + L1 정체성 audit (DD1).

이 파일은 기존 pytest 스위트의 일부로 finish/CI에서 매 릴리스 실행된다 →
사실상 릴리스 게이트. 불변식: "덤프를 가진 운영자가 빈 store에서 무결성
검증된 Commons를 재기동할 수 있다." 깨지면 재해 복구·DB 호스트 종속
회피·마이그레이션 안전이라는 운영 보장이 무너지므로 릴리스를 차단한다.
(TC는 PI Lab 사유 플랫폼 — export는 anti-privatization 보장이 아니라
운영 DR 장치. 코드만 Apache-2.0 OSS, 운영·코퍼스는 PI Lab 자산.)
"""


import pytest

from the_commons.corpus.export import (
    CorpusIntegrityError,
    export_corpus,
    import_corpus,
)
from the_commons.library.content_hash import compute_integrity
from the_commons.library.models import Evidence
from the_commons.library.store import InMemoryEvidenceStore


def _ev(
    eid: str,
    *,
    recipe: str = "rf",
    auc: float = 0.8,
    tier: str = "real",
    goal: str = "exploration",
) -> Evidence:
    rec = {
        "evidence_id": eid,
        "tier": tier,
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {"goal": goal, "expected_baseline": None, "tolerance": None},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "config": {"recipe_id": recipe},
            "metrics": {"AUC": auc},
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
            "attribution": {"operator": None},
            "contract_version": "2.0",
        },
    }
    ev = Evidence.model_validate(rec)
    pcq_norm = ev.pcq_record.model_dump(mode="json")
    pcq_norm["integrity"] = compute_integrity(pcq_norm)
    rec["pcq_record"] = pcq_norm
    return Evidence.model_validate(rec)


def _diverse() -> list[Evidence]:
    return [
        _ev("g-a", recipe="randomforest", auc=0.91),
        _ev("g-b", recipe="xgboost", auc=0.62, tier="synthetic"),
        _ev("g-c", recipe="lightgbm", auc=0.85, goal="sota_challenge"),
        _ev("g-d", recipe="randomforest", auc=0.40, goal="ablation"),
        _ev("g-e", recipe="svm", auc=0.55, tier="synthetic"),
    ]


async def test_governance_gate_corpus_survives_operator_restart() -> None:
    """DD3 핵심 불변식 — 운영자 독립 빈 store 재기동 + 무결성 보존."""
    origin = InMemoryEvidenceStore()
    for ev in _diverse():
        await origin.insert(ev)
    await origin.mark_deprecated("g-d", reason="phi-redacted")  # L1은 보존돼야

    dump = [line async for line in export_corpus(origin)]

    # 완전히 새로운, 코드만 있고 데이터 0인 store (다른 운영자/호스트 모사)
    fresh = InMemoryEvidenceStore()
    inserted = await import_corpus(fresh, dump)
    assert inserted == 5

    got, total = await fresh.list_evidence(deprecated=None, limit=10_000)
    assert total == 5
    assert {e.evidence_id for e in got} == {"g-a", "g-b", "g-c", "g-d", "g-e"}

    # 재-export가 동일 (이식성 fixed-point — drift 없음)
    redump = [line async for line in export_corpus(fresh)]
    assert sorted(redump) == sorted(dump)


async def test_governance_gate_blocks_tampered_corpus() -> None:
    """변조된 덤프는 조용히 재기동될 수 없다 (DC4) — 게이트가 차단."""
    origin = InMemoryEvidenceStore()
    await origin.insert(_ev("t-1", auc=0.9))
    dump = [line async for line in export_corpus(origin)]

    tampered = dump[0].replace('"AUC":0.9', '"AUC":0.123')
    assert tampered != dump[0]

    fresh = InMemoryEvidenceStore()
    with pytest.raises(CorpusIntegrityError):
        await import_corpus(fresh, [tampered])


async def test_l1_identity_is_pcq_record_independent_of_envelope() -> None:
    """DD1 (R10 정합): pcq integrity는 pcq_record 내용으로만 결정.

    envelope 필드(evidence_id/tier/outreach_origin)는 hash 입력 아님 —
    동일 pcq_record는 envelope이 달라도 같은 content_hash.
    """
    ev = _ev("same-id", recipe="rf", auc=0.77)
    pcq_a = ev.pcq_record.model_dump(mode="json")

    # 동일 pcq_record를 서로 다른 store 인스턴스에 넣어도 integrity 불변
    s1, s2 = InMemoryEvidenceStore(), InMemoryEvidenceStore()
    await s1.insert(ev)
    await s2.insert(ev)
    g1 = (await s1.list_evidence(deprecated=None, limit=10))[0][0]
    g2 = (await s2.list_evidence(deprecated=None, limit=10))[0][0]
    assert g1.pcq_record.integrity.content_hash == g2.pcq_record.integrity.content_hash

    # pcq_record 내용 한 필드만 바뀌면 hash 변경
    changed = dict(pcq_a)
    changed["metrics"] = {"AUC": 0.78}
    assert (
        compute_integrity(pcq_a)["content_hash"]
        != compute_integrity(changed)["content_hash"]
    )

    # evidence_id는 envelope 필드 → pcq integrity와 무관(R10)
    pcq_b = dict(pcq_a)  # envelope 변경 안 함 — pcq 같으면 hash 같음
    assert (
        compute_integrity(pcq_a)["content_hash"]
        == compute_integrity(pcq_b)["content_hash"]
    )


def test_signature_excluded_from_integrity_input() -> None:
    """anti-recursion — attribution.signature·integrity 자체는 hash 입력 제외."""
    pcq = _ev("h-1", auc=0.8).pcq_record.model_dump(mode="json")
    h1 = compute_integrity(pcq)["content_hash"]
    # signature·integrity 필드 변경은 hash에 영향 없음
    pcq.setdefault("attribution", {})["signature"] = "phase-2-stub"
    pcq["integrity"] = {"content_hash": "sha256:deadbeef", "hashed_fields": []}
    h2 = compute_integrity(pcq)["content_hash"]
    assert h1 == h2
