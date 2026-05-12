"""promote / contradicts event 기록 검증."""

from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore
from the_commons.reciprocity.promote_contradict import evaluate_and_record


def _real(eid: str, auc: float) -> dict:
    """real evidence dict — 비교용 minimal."""
    return {
        "evidence_id": eid,
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "intent": {"goal": "sota_challenge"},
        "metrics": {"AUC": auc},
    }


def _synthetic(
    eid: str,
    expected: float,
    margin: float = 0.05,
) -> dict:
    """synthetic evidence dict with expected_baseline."""
    return {
        "evidence_id": eid,
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "intent": {
            "goal": "sota_challenge",
            "expected_baseline": {"metric": "AUC", "value": expected},
            "tolerance": {"direction": "higher_is_better", "margin": margin},
        },
        "metrics": {"AUC": expected},
    }


async def test_promote_when_real_metric_within_margin() -> None:
    """real metric이 synthetic 예측과 tolerance 내 일치 → promote event."""
    store = InMemoryReciprocityEventStore()
    grouped = await evaluate_and_record(
        store,
        new_real_record=_real("ev-real-1", auc=0.86),
        candidate_synthetic_records=[_synthetic("ev-syn-1", expected=0.85)],
        origin="external",
    )

    assert grouped["promote"] == ["ev-syn-1"]
    assert grouped["contradicts"] == []
    assert len(store.events) == 1
    assert store.events[0].event_type == "promote"
    assert store.events[0].primary_evidence_id == "ev-real-1"
    assert store.events[0].related_evidence_ids == ["ev-syn-1"]


async def test_contradicts_when_real_outside_margin() -> None:
    """tolerance 밖 차이 → contradicts event."""
    store = InMemoryReciprocityEventStore()
    grouped = await evaluate_and_record(
        store,
        new_real_record=_real("ev-real-1", auc=0.70),
        candidate_synthetic_records=[_synthetic("ev-syn-1", expected=0.85)],
        origin="external",
    )

    assert grouped["contradicts"] == ["ev-syn-1"]
    assert grouped["promote"] == []
    assert store.events[0].event_type == "contradicts"


async def test_indeterminate_does_not_record_event() -> None:
    """indeterminate은 event 기록 안 함 (검증 자체 불가능)."""
    store = InMemoryReciprocityEventStore()
    syn_no_baseline = {
        "evidence_id": "ev-syn-x",
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "intent": {"goal": "exploration"},
        "metrics": {},
    }
    grouped = await evaluate_and_record(
        store,
        new_real_record=_real("ev-real-1", auc=0.85),
        candidate_synthetic_records=[syn_no_baseline],
        origin="internal",
    )

    assert grouped["indeterminate"] == ["ev-syn-x"]
    assert grouped["promote"] == []
    assert grouped["contradicts"] == []
    assert store.events == []


async def test_evaluates_all_candidates_in_one_call() -> None:
    """여러 synthetic을 한 번에 평가하고 각각 적절한 event를 기록."""
    store = InMemoryReciprocityEventStore()
    candidates = [
        _synthetic("ev-syn-1", expected=0.85),  # promote (0.84)
        _synthetic("ev-syn-2", expected=0.50),  # contradicts (0.84 vs 0.50)
        _synthetic("ev-syn-3", expected=0.83),  # promote
    ]
    grouped = await evaluate_and_record(
        store,
        new_real_record=_real("ev-real-1", auc=0.84),
        candidate_synthetic_records=candidates,
        origin="external",
    )

    assert set(grouped["promote"]) == {"ev-syn-1", "ev-syn-3"}
    assert grouped["contradicts"] == ["ev-syn-2"]
    assert len(store.events) == 3
