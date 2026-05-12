"""Composer — corpus 요약, 신뢰도 분류, candidate 조립 단위 테스트."""

from datetime import UTC, datetime

import pytest

from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import (
    Evidence,
)
from the_commons.llm.protocol import RankedCandidate
from the_commons.matchmaker.composer import (
    CorpusContext,
    classify_confidence,
    compose_candidates,
    summarize_corpus,
)
from the_commons.matchmaker.retriever import RetrievedHit


def _evidence(eid: str, recipe: str = "lightgbm", auc: float = 0.85) -> Evidence:
    rec_dict = {
        "evidence_id": eid,
        "tier": "real",
        "outreach_origin": "external",
        "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count_band": "10k-100k",
            "schema_summary": {},
            "statistical_moments": {},
        },
        "config": {"recipe_id": recipe},
        "metrics": {"AUC": auc},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {
            "contributor_id": None,
            "content_hash": "",
            "created_at": datetime.now(UTC).isoformat(),
            "pcq_version": "2.0.0",
        },
        "synthetic_source": None,
    }
    rec_dict["attribution"]["content_hash"] = compute_content_hash(rec_dict)
    return Evidence.model_validate(rec_dict)


def test_summarize_corpus_counts_by_tier() -> None:
    """real/synthetic 비율 카운팅."""
    hits = [
        RetrievedHit(evidence_id="a", similarity=0.9, tier="real"),
        RetrievedHit(evidence_id="b", similarity=0.8, tier="synthetic"),
        RetrievedHit(evidence_id="c", similarity=0.7, tier="synthetic"),
    ]
    ctx = summarize_corpus(hits)
    assert ctx.real_count == 1
    assert ctx.synthetic_count == 2
    assert ctx.total == 3


def test_corpus_context_synthetic_dominant_property() -> None:
    """synthetic이 real보다 많으면 dominant."""
    assert CorpusContext(real_count=2, synthetic_count=5).is_synthetic_dominant is True
    assert CorpusContext(real_count=5, synthetic_count=2).is_synthetic_dominant is False
    assert CorpusContext(real_count=0, synthetic_count=0).is_synthetic_dominant is False


@pytest.mark.parametrize(
    ("real", "synth", "heuristic", "expected"),
    [
        (5, 0, False, "strong"),
        (3, 1, False, "strong"),
        (2, 0, False, "medium"),
        (1, 5, False, "synthetic_dominant"),  # synthetic dominant 우선
        (0, 0, True, "weak_heuristic"),
        (10, 0, True, "weak_heuristic"),  # heuristic 플래그 우선
    ],
)
def test_classify_confidence(
    real: int, synth: int, heuristic: bool, expected: str
) -> None:
    """confidence 라벨 분류 규칙."""
    ctx = CorpusContext(real_count=real, synthetic_count=synth)
    assert classify_confidence(ctx, is_heuristic_fallback=heuristic) == expected


def test_compose_candidates_maps_index_to_evidence() -> None:
    """RankedCandidate.index가 fetched_evidence list의 위치를 가리킨다."""
    fetched = [_evidence("ev-a", recipe="lightgbm"), _evidence("ev-b", recipe="xgboost")]
    ranked = [
        RankedCandidate(index=1, score=0.95, reasoning="xgboost wins"),
        RankedCandidate(index=0, score=0.80, reasoning="lightgbm runner-up"),
    ]
    composed = compose_candidates(ranked, fetched_evidence=fetched, confidence="strong")

    assert len(composed) == 2
    assert composed[0].recipe_id == "xgboost"
    assert composed[0].evidence_ids == ["ev-b"]
    assert composed[1].recipe_id == "lightgbm"
    assert composed[0].confidence == "strong"


def test_compose_candidates_skips_out_of_range_index() -> None:
    """잘못된 index는 무시."""
    fetched = [_evidence("ev-a")]
    ranked = [
        RankedCandidate(index=99, score=0.9, reasoning="bad"),
        RankedCandidate(index=0, score=0.7, reasoning="ok"),
    ]
    composed = compose_candidates(ranked, fetched_evidence=fetched, confidence="medium")
    assert len(composed) == 1
    assert composed[0].evidence_ids == ["ev-a"]


def test_compose_candidates_extracts_primary_metric() -> None:
    """첫 numeric metric을 expected_metric으로 옮긴다."""
    fetched = [_evidence("ev-a", recipe="lightgbm", auc=0.847)]
    ranked = [RankedCandidate(index=0, score=0.9, reasoning="ok")]
    composed = compose_candidates(ranked, fetched_evidence=fetched, confidence="strong")
    assert composed[0].expected_metric == {"name": "AUC", "value": 0.847}
