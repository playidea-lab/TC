"""코퍼스 거버넌스 릴리스 게이트 (DD3) + L1 정체성 audit (DD1).

이 파일은 기존 pytest 스위트의 일부로 finish/CI에서 매 릴리스 실행된다 →
사실상 릴리스 게이트. 불변식: "덤프를 가진 누구나, 운영자와 독립적으로,
빈 store에서 무결성 검증된 Commons를 재기동할 수 있다." 깨지면 거버넌스
약속("도서관은 운영자보다 오래 산다 / PI Lab 사유 아님")이 정책 문구로
전락하므로 릴리스를 차단한다.
"""

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
        "intent": {"goal": goal, "expected_baseline": None, "tolerance": None},
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


async def test_l1_identity_is_content_not_storage() -> None:
    """DD1 — content_hash는 record 내용으로 결정, 저장 위치/인스턴스 무관."""
    ev = _ev("same-id", recipe="rf", auc=0.77)
    da = ev.model_dump(mode="json")

    # 동일 레코드를 *서로 다른 store 인스턴스*에 넣어도 hash 불변
    # (정체성은 내용이지 저장 위치/row가 아니다 — 운영자 독립의 핵심)
    s1, s2 = InMemoryEvidenceStore(), InMemoryEvidenceStore()
    await s1.insert(ev)
    await s2.insert(ev)
    g1 = (await s1.list_evidence(deprecated=None, limit=10))[0][0]
    g2 = (await s2.list_evidence(deprecated=None, limit=10))[0][0]
    assert compute_content_hash(g1.model_dump(mode="json")) == compute_content_hash(
        g2.model_dump(mode="json")
    )

    # 한 필드만 바뀌면 hash 변경
    changed = dict(da)
    changed["metrics"] = {"AUC": 0.78}
    assert compute_content_hash(da) != compute_content_hash(changed)

    # evidence_id도 L1 내용의 일부 — 바뀌면 hash 변경 (DoD의 "id 무관 hash
    # 동일"은 부정확: 정체성은 내용이며 evidence_id는 그 내용에 포함된다)
    relabeled = dict(da)
    relabeled["evidence_id"] = "other-id"
    assert compute_content_hash(da) != compute_content_hash(relabeled)


def test_attribution_content_hash_excluded_from_hash_input() -> None:
    """chicken-egg — attribution.content_hash 자체는 hash 입력서 제외."""
    base = _ev("h-1", auc=0.8).model_dump(mode="json")
    h1 = compute_content_hash(base)
    base["attribution"]["content_hash"] = "sha256:deadbeef"  # 임의 변경
    h2 = compute_content_hash(base)
    assert h1 == h2  # content_hash 필드 변경은 hash에 영향 없음
