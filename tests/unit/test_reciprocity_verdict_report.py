"""3-event verdict report 산정."""

from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore
from the_commons.reciprocity.verdict_report import build_verdict_report


async def test_verdict_failure_with_zero_events() -> None:
    """0 event → failure (비전 재검토). counts_by_origin은 internal/external 모두 0."""
    store = InMemoryReciprocityEventStore()
    report = await build_verdict_report(store)

    assert report.branch == "failure"
    assert report.is_success is False
    assert "vision revision" in report.detail
    # A.5 — Postgres GROUP BY가 빈 origin을 omit해도 응답엔 항상 두 key 노출
    assert report.counts_by_origin["internal"] == 0
    assert report.counts_by_origin["external"] == 0


async def test_verdict_partial_with_only_loop_closure() -> None:
    """loop_closure만 있고 promote/contradicts 없음 → partial."""
    store = InMemoryReciprocityEventStore()
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )

    report = await build_verdict_report(store)
    assert report.branch == "partial"
    assert report.counts["loop_closure"] == 1
    assert report.counts["promote_or_contradict"] == 0


async def test_verdict_success_with_both_axes() -> None:
    """loop_closure + promote → success."""
    store = InMemoryReciprocityEventStore()
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )
    await store.record(
        event_type="promote",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-1"],
        origin="external",
    )

    report = await build_verdict_report(store)
    assert report.branch == "success"
    assert report.is_success is True
    assert report.counts["promote"] == 1


async def test_strengthened_success_when_external_origin_present() -> None:
    """external origin event 1건 이상 시 strengthened=True."""
    store = InMemoryReciprocityEventStore()
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )
    await store.record(
        event_type="contradicts",
        primary_evidence_id="ev-real-2",
        related_evidence_ids=["ev-syn-2"],
        origin="internal",
    )

    report = await build_verdict_report(store)
    assert report.branch == "success"
    assert report.strengthened is True
    assert report.counts_by_origin["external"] >= 1


async def test_not_strengthened_when_only_internal_events() -> None:
    """internal만 있으면 strengthened=False (self-staged 한정)."""
    store = InMemoryReciprocityEventStore()
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="internal",
    )
    await store.record(
        event_type="promote",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-1"],
        origin="internal",
    )

    report = await build_verdict_report(store)
    assert report.branch == "success"
    assert report.strengthened is False


async def test_contradicts_counts_toward_promote_or_contradict_axis() -> None:
    """contradicts도 promote_or_contradict 축에 카운트 (음성 결과 1급)."""
    store = InMemoryReciprocityEventStore()
    await store.record(
        event_type="loop_closure",
        primary_evidence_id="ev-a",
        related_evidence_ids=[],
        origin="external",
    )
    await store.record(
        event_type="contradicts",
        primary_evidence_id="ev-real-1",
        related_evidence_ids=["ev-syn-1"],
        origin="external",
    )

    report = await build_verdict_report(store)
    assert report.branch == "success"
    assert report.counts["promote_or_contradict"] == 1
