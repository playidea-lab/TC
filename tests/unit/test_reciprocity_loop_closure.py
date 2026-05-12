"""loop closure event 기록 검증."""

from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore
from the_commons.reciprocity.loop_closure import record_loop_closures


async def test_records_one_event_per_cited_evidence() -> None:
    """응답에 evidence 3개가 포함되면 loop_closure event 3건 기록."""
    store = InMemoryReciprocityEventStore()
    count = await record_loop_closures(
        store,
        consumer_contributor_id="k2",
        consumer_origin="external",
        cited_evidence_ids=["ev-a", "ev-b", "ev-c"],
        cluster_bucket="tabular-exploration-10k-100k",
    )

    assert count == 3
    assert len(store.events) == 3
    assert all(e.event_type == "loop_closure" for e in store.events)
    assert {e.primary_evidence_id for e in store.events} == {"ev-a", "ev-b", "ev-c"}
    assert all(e.origin == "external" for e in store.events)


async def test_records_zero_when_no_evidence_cited() -> None:
    """휴리스틱 fallback 응답은 evidence_ids가 비어있어 event 0건."""
    store = InMemoryReciprocityEventStore()
    count = await record_loop_closures(
        store,
        consumer_contributor_id="k2",
        consumer_origin="external",
        cited_evidence_ids=[],
    )
    assert count == 0
    assert store.events == []


async def test_metadata_includes_consumer_id_and_bucket() -> None:
    """기록된 event metadata에 consumer + cluster context 포함."""
    store = InMemoryReciprocityEventStore()
    await record_loop_closures(
        store,
        consumer_contributor_id="user-42",
        consumer_origin="external",
        cited_evidence_ids=["ev-x"],
        cluster_bucket="vision-sota_challenge-100k-1M",
    )

    event = store.events[0]
    assert event.metadata["consumer_contributor_id"] == "user-42"
    assert event.metadata["cluster_bucket"] == "vision-sota_challenge-100k-1M"
