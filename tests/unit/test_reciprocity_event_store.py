"""InMemoryReciprocityEventStore 동작 검증."""

import pytest

from the_commons.reciprocity.event_store import (
    InMemoryReciprocityEventStore,
    ReciprocityEventStore,
)


@pytest.fixture
def store() -> InMemoryReciprocityEventStore:
    return InMemoryReciprocityEventStore()


def test_in_memory_store_is_protocol_compatible(
    store: InMemoryReciprocityEventStore,
) -> None:
    assert isinstance(store, ReciprocityEventStore)


async def test_record_assigns_sequential_ids(
    store: InMemoryReciprocityEventStore,
) -> None:
    """기록할 때마다 event_id 1씩 증가."""
    e1 = await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )
    e2 = await store.record(
        event_type="promote",
        primary_evidence_id="ev-b",
        related_evidence_ids=["ev-c"],
        origin="internal",
    )
    assert e1.event_id == 1
    assert e2.event_id == 2


async def test_count_by_type_groups_correctly(
    store: InMemoryReciprocityEventStore,
) -> None:
    """type별 카운트가 정확."""
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-b",
        related_evidence_ids=[],
        origin="external",
    )
    await store.record(
        event_type="promote",
        primary_evidence_id="ev-c",
        related_evidence_ids=["ev-syn-1"],
        origin="internal",
    )

    counts = await store.count_by_type()
    assert counts["loop_closure"] == 2
    assert counts["promote"] == 1
    assert counts["contradicts"] == 0


async def test_count_by_origin_groups_correctly(
    store: InMemoryReciprocityEventStore,
) -> None:
    """origin별 카운트 — verdict 강화된 성공 측정 기준."""
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-b",
        related_evidence_ids=[],
        origin="internal",
    )
    await store.record(
        event_type="contradicts",
        primary_evidence_id="ev-c",
        related_evidence_ids=["ev-syn-1"],
        origin="external",
    )

    counts = await store.count_by_origin()
    assert counts["external"] == 2
    assert counts["internal"] == 1


async def test_record_stores_metadata_and_related_ids(
    store: InMemoryReciprocityEventStore,
) -> None:
    """metadata + related_ids가 저장되고 immutable list."""
    event = await store.record(
        event_type="promote",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-1", "ev-syn-2"],
        origin="external",
        metadata={"cluster_bucket": "tabular-exploration-10k-100k"},
    )
    assert event.related_evidence_ids == ["ev-syn-1", "ev-syn-2"]
    assert event.metadata["cluster_bucket"] == "tabular-exploration-10k-100k"


async def test_find_verifier_for_returns_promoting_real(
    store: InMemoryReciprocityEventStore,
) -> None:
    """promote event 기록 후 find_verifier_for가 해당 real_id 반환."""
    await store.record(
        event_type="promote",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )
    assert await store.find_verifier_for("ev-syn-target") == "ev-real-1"


async def test_find_verifier_for_returns_contradicting_real(
    store: InMemoryReciprocityEventStore,
) -> None:
    """contradicts도 verifier로 간주 — 검증은 했음, 결과만 반대."""
    await store.record(
        event_type="contradicts",
        primary_evidence_id="ev-real-2",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )
    assert await store.find_verifier_for("ev-syn-target") == "ev-real-2"


async def test_find_verifier_for_returns_none_when_only_loop_closure(
    store: InMemoryReciprocityEventStore,
) -> None:
    """loop_closure event는 verifier 아님 — None 반환."""
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-real-x",
        related_evidence_ids=["ev-syn-target"],
        origin="external",
    )
    assert await store.find_verifier_for("ev-syn-target") is None


async def test_find_verifier_for_returns_none_when_unrelated(
    store: InMemoryReciprocityEventStore,
) -> None:
    """다른 synthetic_id를 검증한 event는 영향 없음."""
    await store.record(
        event_type="promote",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-other"],
        origin="external",
    )
    assert await store.find_verifier_for("ev-syn-target") is None
