"""infogain.reranker — InfoGainReranker orchestrator 단위 테스트."""

from datetime import UTC, datetime

from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import Evidence
from the_commons.matchmaker.infogain.llm_prior import WEAK_DEFAULT_PRIOR
from the_commons.matchmaker.infogain.reranker import InfoGainReranker
from the_commons.matchmaker.retriever import RetrievedHit


class _StubLLM:
    """저데이터 regime에서 호출될 수 있는 prior LLM. 약한 prior 반환."""

    async def complete(self, prompt: str) -> str:
        return '{"alpha": 1.0, "beta": 1.0}'


def _ev(eid: str, recipe: str, auc: float, tier: str = "real") -> Evidence:
    rec = {
        "evidence_id": eid,
        "tier": tier,
        "outreach_origin": "external",
        "intent": {
            "goal": "exploration",
            "expected_baseline": {"metric": "AUC"},
            "tolerance": {"direction": "higher_is_better"},
        },
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


def _hits(records: list[Evidence]) -> list[RetrievedHit]:
    return [
        RetrievedHit(evidence_id=ev.evidence_id, similarity=0.9, tier=ev.tier)
        for ev in records
    ]


async def test_rerank_returns_valid_indices_into_records() -> None:
    records = [_ev("a", "rf", 0.9), _ev("b", "xgb", 0.6), _ev("c", "rf", 0.4)]
    rr = InfoGainReranker(llm=_StubLLM())
    ranked = await rr.rerank("q", _hits(records), records, top_n=3)
    assert {r.index for r in ranked} <= {0, 1, 2}
    assert len(ranked) == 3


async def test_top_n_truncation() -> None:
    records = [_ev(f"e{i}", f"r{i}", 0.5 + i * 0.05) for i in range(6)]
    rr = InfoGainReranker(llm=_StubLLM())
    ranked = await rr.rerank("q", _hits(records), records, top_n=2)
    assert len(ranked) == 2


async def test_ranked_descending_by_info_gain() -> None:
    records = [_ev(f"e{i}", f"r{i}", 0.5) for i in range(4)]
    rr = InfoGainReranker(llm=_StubLLM())
    ranked = await rr.rerank("q", _hits(records), records, top_n=4)
    scores = [r.score for r in ranked]
    # score = recipe expected_info_gain → 내림차순
    assert scores == sorted(scores, reverse=True)


async def test_sharp_negative_recipe_ranks_below_uncertain_recipe() -> None:
    # rf: real 음성 다수(>=threshold) → 뾰족한 낮은 사후 → 낮은 정보이득
    # xgb: 관측 1건 → 불확실 → 높은 정보이득 → 상위
    records = [
        _ev("n1", "rf", 0.0),
        _ev("n2", "rf", 0.05),
        _ev("n3", "rf", 0.0),
        _ev("n4", "rf", 0.1),
        _ev("u1", "xgb", 0.5),
    ]
    rr = InfoGainReranker(llm=_StubLLM())
    ranked = await rr.rerank("q", _hits(records), records, top_n=5)
    order = [r.index for r in ranked]
    xgb_idx = 4
    rf_idxs = [0, 1, 2, 3]
    # xgb(불확실)가 모든 rf(뾰족한 음성)보다 위
    assert order.index(xgb_idx) < min(order.index(i) for i in rf_idxs)


async def test_reasoning_contains_posterior_and_infogain() -> None:
    records = [_ev("a", "rf", 0.8)]
    rr = InfoGainReranker(llm=_StubLLM())
    ranked = await rr.rerank("q", _hits(records), records, top_n=1)
    text = ranked[0].reasoning.lower()
    assert "mean" in text or "평균" in text
    assert "gain" in text or "정보이득" in text


async def test_empty_records_returns_empty() -> None:
    rr = InfoGainReranker(llm=_StubLLM())
    ranked = await rr.rerank("q", [], [], top_n=5)
    assert ranked == []


def test_weak_default_constant_is_uniform() -> None:
    assert WEAK_DEFAULT_PRIOR == (1.0, 1.0)
