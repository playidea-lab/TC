"""Retirement worker — cluster density 모니터링 + synthetic deprecate + audit log.

ingest 직후 트리거 또는 주기적 실행 (settings.retirement_check_interval_sec).
모든 DB 작업은 Protocol을 통과 → 단위 테스트는 fake로 가능.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from the_commons.retirement.policy import (
    RetirementCandidate,
    select_synthetics_to_retire,
    should_retire,
)
from the_commons.settings import settings


@dataclass(frozen=True)
class RetirementAuditEntry:
    """retirement_audit 테이블 한 행."""

    retirement_id: int
    synthetic_evidence_id: str
    cluster_id: str
    triggered_by_real_ids: list[str]
    retired_at: datetime


@runtime_checkable
class RetirementBackend(Protocol):
    """retirement worker가 의존하는 DB 작업 묶음."""

    async def get_active_synthetics_in_cluster(
        self, cluster_id: str
    ) -> list[dict[str, Any]]: ...

    async def get_cluster_real_count(self, cluster_id: str) -> int: ...

    async def mark_deprecated(
        self, synthetic_evidence_id: str, *, reason: str
    ) -> None: ...

    async def record_audit(
        self, candidate: RetirementCandidate
    ) -> RetirementAuditEntry: ...


# ----------------------------------------------------------------------------
# In-memory backend (test/local)
# ----------------------------------------------------------------------------


@dataclass
class InMemoryRetirementBackend:
    """test·로컬용. retirement 정책 검증에 충분."""

    active_synthetics_by_cluster: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    real_count_by_cluster: dict[str, int] = field(default_factory=dict)

    deprecated_ids: list[str] = field(default_factory=list)
    audit_entries: list[RetirementAuditEntry] = field(default_factory=list)
    _next_id: int = 1

    async def get_active_synthetics_in_cluster(
        self, cluster_id: str
    ) -> list[dict[str, Any]]:
        return list(self.active_synthetics_by_cluster.get(cluster_id, []))

    async def get_cluster_real_count(self, cluster_id: str) -> int:
        return self.real_count_by_cluster.get(cluster_id, 0)

    async def mark_deprecated(
        self, synthetic_evidence_id: str, *, reason: str
    ) -> None:
        self.deprecated_ids.append(synthetic_evidence_id)
        # active list에서도 제거 (다음 호출에서 중복 retirement 방지)
        for cluster_id, items in self.active_synthetics_by_cluster.items():
            self.active_synthetics_by_cluster[cluster_id] = [
                s for s in items if s.get("evidence_id") != synthetic_evidence_id
            ]
        _ = reason

    async def record_audit(
        self, candidate: RetirementCandidate
    ) -> RetirementAuditEntry:
        entry = RetirementAuditEntry(
            retirement_id=self._next_id,
            synthetic_evidence_id=candidate.synthetic_evidence_id,
            cluster_id=candidate.cluster_id,
            triggered_by_real_ids=list(candidate.triggered_by_real_ids),
            retired_at=datetime.now(UTC),
        )
        self.audit_entries.append(entry)
        self._next_id += 1
        return entry


# ----------------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------------


class RetirementWorker:
    """cluster density 모니터링 + synthetic deprecate."""

    def __init__(
        self,
        backend: RetirementBackend,
        *,
        threshold: int | None = None,
    ) -> None:
        self._backend = backend
        self._threshold = threshold or settings.retirement_real_threshold

    async def check_cluster(
        self,
        cluster_id: str,
        *,
        triggered_by_real_ids: list[str],
    ) -> list[RetirementAuditEntry]:
        """cluster의 real_count가 임계값을 넘었으면 active synthetic을 모두 deprecate.

        Returns: 새로 기록된 audit entries (이미 retired였던 synthetic은 미포함).
        """
        real_count = await self._backend.get_cluster_real_count(cluster_id)
        if not should_retire(real_count, threshold=self._threshold):
            return []

        active = await self._backend.get_active_synthetics_in_cluster(cluster_id)
        if not active:
            return []

        candidates = select_synthetics_to_retire(
            active,
            cluster_id=cluster_id,
            triggered_by_real_ids=triggered_by_real_ids,
        )
        retired_entries: list[RetirementAuditEntry] = []
        for c in candidates:
            await self._backend.mark_deprecated(
                c.synthetic_evidence_id,
                reason=(
                    f"cluster {cluster_id} real_count reached {real_count} "
                    f"(threshold {self._threshold})"
                ),
            )
            entry = await self._backend.record_audit(c)
            retired_entries.append(entry)
        return retired_entries
