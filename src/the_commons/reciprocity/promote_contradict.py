"""promote / contradicts event 기록.

새 real evidence가 ingest되면 같은 cluster의 active synthetic을 평가해
promote(일치) 또는 contradicts(불일치) event를 기록한다.

비교 자체는 cluster_impact.evaluate_synthetic_match 재사용.
"""

from typing import Any

from the_commons.ingestion.cluster_impact import (
    MatchOutcome,
    compute_problem_cluster_bucket,
    evaluate_synthetic_match,
)
from the_commons.reciprocity.event_store import ReciprocityEventStore


async def evaluate_and_record(
    store: ReciprocityEventStore,
    *,
    new_real_record: dict[str, Any],
    candidate_synthetic_records: list[dict[str, Any]],
    origin: str,
) -> dict[MatchOutcome, list[str]]:
    """새 real이 들어왔을 때 candidate synthetics를 평가해 event 기록.

    Args:
        store: event store
        new_real_record: 방금 ingest된 real evidence
        candidate_synthetic_records: 같은 cluster의 활성 synthetic 후보들
        origin: 새 real evidence의 outreach_origin

    Returns:
        outcome별 처리된 synthetic evidence_id 목록 (promote / contradicts /
        indeterminate)
    """
    cluster_bucket = compute_problem_cluster_bucket(new_real_record)
    real_evidence_id = new_real_record.get("evidence_id", "")

    grouped: dict[MatchOutcome, list[str]] = {
        "promote": [],
        "contradicts": [],
        "indeterminate": [],
    }

    for syn in candidate_synthetic_records:
        outcome = evaluate_synthetic_match(new_real_record, syn)
        syn_id = syn.get("evidence_id", "")
        grouped[outcome].append(syn_id)

        if outcome == "indeterminate":
            continue

        await store.record(
            event_type=outcome,  # "promote" or "contradicts"
            primary_evidence_id=real_evidence_id,
            related_evidence_ids=[syn_id],
            origin=origin,
            metadata={"cluster_bucket": cluster_bucket},
        )

    return grouped
