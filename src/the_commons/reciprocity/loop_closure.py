"""loop closure event 기록.

K2가 추천 응답을 받았을 때, 응답에 포함된 evidence_ids가 *각각* loop closure
event를 생성한다. 응답을 받는 contributor의 origin이 event origin이 된다
(verdict 강화된 성공의 external 카운트 기여).
"""

from typing import Any

from the_commons.reciprocity.event_store import ReciprocityEventStore


async def record_loop_closures(
    store: ReciprocityEventStore,
    *,
    consumer_contributor_id: str | None,
    consumer_origin: str,
    cited_evidence_ids: list[str],
    cluster_bucket: str | None = None,
) -> int:
    """추천 응답에 포함된 evidence_ids 각각에 loop closure event 기록.

    Args:
        store: event store
        consumer_contributor_id: 추천을 받은 사용자 (none이면 anonymous)
        consumer_origin: 'internal' | 'external' — verdict 강화 측정 기준
        cited_evidence_ids: 응답의 근거 evidence_ids (휴리스틱이면 빈 list)
        cluster_bucket: optional context

    Returns:
        기록된 event 개수
    """
    if not cited_evidence_ids:
        return 0

    metadata: dict[str, Any] = {
        "consumer_contributor_id": consumer_contributor_id,
    }
    if cluster_bucket:
        metadata["cluster_bucket"] = cluster_bucket

    count = 0
    for evidence_id in cited_evidence_ids:
        await store.record(
            event_type="loop_closure",
            primary_evidence_id=evidence_id,
            related_evidence_ids=[],
            origin=consumer_origin,
            metadata=metadata,
        )
        count += 1
    return count
