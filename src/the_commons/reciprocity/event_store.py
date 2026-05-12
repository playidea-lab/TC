"""ReciprocityEventStore — event 기록 인터페이스.

Protocol 추상화로 DB 없이 unit test 가능.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

import psycopg

EventType = Literal["loop_closure", "promote", "contradicts"]


@dataclass(frozen=True)
class ReciprocityEvent:
    """기록된 event 한 항목."""

    event_id: int
    event_type: EventType
    primary_evidence_id: str
    related_evidence_ids: list[str]
    metadata: dict[str, Any]
    origin: str  # 'internal' | 'external'
    created_at: datetime


@runtime_checkable
class ReciprocityEventStore(Protocol):
    """event 기록 인터페이스."""

    async def record(
        self,
        *,
        event_type: EventType,
        primary_evidence_id: str,
        related_evidence_ids: list[str],
        origin: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReciprocityEvent: ...

    async def count_by_type(self) -> dict[EventType, int]:
        """각 event type별 누적 카운트. verdict report용."""
        ...

    async def count_by_origin(self) -> dict[str, int]:
        """origin별 누적 카운트 (internal vs external)."""
        ...


# ----------------------------------------------------------------------------
# In-memory
# ----------------------------------------------------------------------------


@dataclass
class InMemoryReciprocityEventStore:
    """단위 테스트 + Phase 0 운영용 in-memory 구현체."""

    events: list[ReciprocityEvent] = field(default_factory=list)
    _next_id: int = 1

    async def record(
        self,
        *,
        event_type: EventType,
        primary_evidence_id: str,
        related_evidence_ids: list[str],
        origin: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReciprocityEvent:
        event = ReciprocityEvent(
            event_id=self._next_id,
            event_type=event_type,
            primary_evidence_id=primary_evidence_id,
            related_evidence_ids=list(related_evidence_ids),
            metadata=metadata or {},
            origin=origin,
            created_at=datetime.now(UTC),
        )
        self.events.append(event)
        self._next_id += 1
        return event

    async def count_by_type(self) -> dict[EventType, int]:
        out: dict[EventType, int] = {"loop_closure": 0, "promote": 0, "contradicts": 0}
        for e in self.events:
            out[e.event_type] += 1
        return out

    async def count_by_origin(self) -> dict[str, int]:
        out: dict[str, int] = {"internal": 0, "external": 0}
        for e in self.events:
            out[e.origin] = out.get(e.origin, 0) + 1
        return out


# ----------------------------------------------------------------------------
# PostgreSQL
# ----------------------------------------------------------------------------


_INSERT_SQL = """
INSERT INTO reciprocity_event (
    event_type, primary_evidence_id, related_evidence_ids, metadata, origin
)
VALUES (%s, %s, %s, %s, %s)
RETURNING event_id, created_at
"""

_COUNT_BY_TYPE_SQL = (
    "SELECT event_type::text, COUNT(*) FROM reciprocity_event GROUP BY event_type"
)

_COUNT_BY_ORIGIN_SQL = (
    "SELECT origin::text, COUNT(*) FROM reciprocity_event GROUP BY origin"
)


class PostgresReciprocityEventStore:
    """psycopg 3 async 기반 PostgreSQL 구현체."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def record(
        self,
        *,
        event_type: EventType,
        primary_evidence_id: str,
        related_evidence_ids: list[str],
        origin: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReciprocityEvent:
        async with self._conn.cursor() as cur:
            await cur.execute(
                _INSERT_SQL,
                (
                    event_type,
                    primary_evidence_id,
                    json.dumps(related_evidence_ids),
                    json.dumps(metadata or {}),
                    origin,
                ),
            )
            row = await cur.fetchone()
        await self._conn.commit()
        if row is None:
            raise RuntimeError("reciprocity_event INSERT가 결과를 반환하지 않음")
        event_id, created_at = row
        return ReciprocityEvent(
            event_id=event_id,
            event_type=event_type,
            primary_evidence_id=primary_evidence_id,
            related_evidence_ids=list(related_evidence_ids),
            metadata=metadata or {},
            origin=origin,
            created_at=created_at,
        )

    async def count_by_type(self) -> dict[EventType, int]:
        async with self._conn.cursor() as cur:
            await cur.execute(_COUNT_BY_TYPE_SQL)
            rows = await cur.fetchall()
        out: dict[EventType, int] = {"loop_closure": 0, "promote": 0, "contradicts": 0}
        for event_type, count in rows:
            out[event_type] = int(count)
        return out

    async def count_by_origin(self) -> dict[str, int]:
        async with self._conn.cursor() as cur:
            await cur.execute(_COUNT_BY_ORIGIN_SQL)
            rows = await cur.fetchall()
        return {origin: int(count) for origin, count in rows}
