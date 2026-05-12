"""Retirement worker — cluster density 모니터링 + synthetic deprecate."""

import pytest

from the_commons.retirement.policy import (
    select_synthetics_to_retire,
    should_retire,
)
from the_commons.retirement.worker import (
    InMemoryRetirementBackend,
    RetirementBackend,
    RetirementWorker,
)


def test_should_retire_returns_true_at_threshold() -> None:
    """real_count == threshold면 retire."""
    assert should_retire(3, threshold=3) is True
    assert should_retire(2, threshold=3) is False
    assert should_retire(10, threshold=3) is True


def test_select_synthetics_to_retire_builds_candidates() -> None:
    """active synthetic dict 리스트 → RetirementCandidate 리스트."""
    candidates = select_synthetics_to_retire(
        [{"evidence_id": "ev-syn-1"}, {"evidence_id": "ev-syn-2"}, {"no_id": "skip"}],
        cluster_id="c1",
        triggered_by_real_ids=["ev-real-a", "ev-real-b"],
    )
    assert len(candidates) == 2
    assert candidates[0].synthetic_evidence_id == "ev-syn-1"
    assert candidates[0].triggered_by_real_ids == ["ev-real-a", "ev-real-b"]


@pytest.fixture
def backend() -> InMemoryRetirementBackend:
    return InMemoryRetirementBackend()


def test_backend_is_protocol_compatible(backend: InMemoryRetirementBackend) -> None:
    assert isinstance(backend, RetirementBackend)


async def test_check_cluster_below_threshold_does_nothing(
    backend: InMemoryRetirementBackend,
) -> None:
    """real_count가 threshold 미만이면 deprecate 안 함."""
    backend.real_count_by_cluster["c1"] = 2
    backend.active_synthetics_by_cluster["c1"] = [{"evidence_id": "ev-syn-1"}]

    worker = RetirementWorker(backend, threshold=3)
    audit = await worker.check_cluster("c1", triggered_by_real_ids=["ev-r-1"])

    assert audit == []
    assert backend.deprecated_ids == []


async def test_check_cluster_at_threshold_deprecates_all_active_synthetics(
    backend: InMemoryRetirementBackend,
) -> None:
    """threshold 도달 시 active synthetic 모두 deprecate + audit 기록."""
    backend.real_count_by_cluster["c1"] = 3
    backend.active_synthetics_by_cluster["c1"] = [
        {"evidence_id": "ev-syn-1"},
        {"evidence_id": "ev-syn-2"},
    ]

    worker = RetirementWorker(backend, threshold=3)
    audit = await worker.check_cluster(
        "c1",
        triggered_by_real_ids=["ev-r-1", "ev-r-2", "ev-r-3"],
    )

    assert len(audit) == 2
    assert set(backend.deprecated_ids) == {"ev-syn-1", "ev-syn-2"}
    assert audit[0].cluster_id == "c1"
    assert audit[0].triggered_by_real_ids == ["ev-r-1", "ev-r-2", "ev-r-3"]


async def test_check_cluster_with_no_active_synthetics_records_nothing(
    backend: InMemoryRetirementBackend,
) -> None:
    """threshold는 넘었지만 synthetic이 이미 없으면 audit 0."""
    backend.real_count_by_cluster["c1"] = 5
    backend.active_synthetics_by_cluster["c1"] = []

    worker = RetirementWorker(backend, threshold=3)
    audit = await worker.check_cluster("c1", triggered_by_real_ids=["ev-r-1"])

    assert audit == []


async def test_repeated_check_does_not_double_retire(
    backend: InMemoryRetirementBackend,
) -> None:
    """이미 retire된 synthetic은 두 번째 호출에서 audit 안 함."""
    backend.real_count_by_cluster["c1"] = 3
    backend.active_synthetics_by_cluster["c1"] = [{"evidence_id": "ev-syn-1"}]

    worker = RetirementWorker(backend, threshold=3)
    first = await worker.check_cluster("c1", triggered_by_real_ids=["ev-r-1"])
    second = await worker.check_cluster("c1", triggered_by_real_ids=["ev-r-2"])

    assert len(first) == 1
    assert second == []  # 이미 retire됨
