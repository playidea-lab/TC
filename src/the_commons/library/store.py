"""evidence store — L1 immutable storage 인터페이스.

Protocol 추상화로 두 가지 구현체:
- PostgresEvidenceStore: 실제 DB (psycopg 3 async)
- InMemoryEvidenceStore: 단위 테스트용 in-memory

endpoint·ingestion 파이프라인은 Protocol에만 의존 → DB 없이 test 가능.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import psycopg

from the_commons.library.models import Evidence

# ----------------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------------


class EvidenceAlreadyExistsError(ValueError):
    """같은 evidence_id 또는 content_hash가 이미 존재."""


@runtime_checkable
class EvidenceStore(Protocol):
    """L1 immutable evidence storage 인터페이스."""

    async def insert(self, evidence: Evidence) -> None:
        """새 evidence를 immutable로 저장.

        Raises:
            EvidenceAlreadyExistsError: evidence_id 또는 content_hash 충돌
        """
        ...

    async def get_by_id(self, evidence_id: str) -> Evidence | None:
        """ID로 단건 조회. 없으면 None."""
        ...


# ----------------------------------------------------------------------------
# In-memory (test)
# ----------------------------------------------------------------------------


class InMemoryEvidenceStore:
    """단위 테스트용 in-memory 구현체. 같은 schema 제약 (id/hash unique)을 적용."""

    def __init__(self) -> None:
        self._by_id: dict[str, Evidence] = {}
        self._hashes: set[str] = set()

    async def insert(self, evidence: Evidence) -> None:
        if evidence.evidence_id in self._by_id:
            raise EvidenceAlreadyExistsError(
                f"evidence_id 중복: {evidence.evidence_id}"
            )
        if evidence.attribution.content_hash in self._hashes:
            raise EvidenceAlreadyExistsError(
                f"content_hash 중복: {evidence.attribution.content_hash}"
            )
        self._by_id[evidence.evidence_id] = evidence
        self._hashes.add(evidence.attribution.content_hash)

    async def get_by_id(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id)


# ----------------------------------------------------------------------------
# PostgreSQL
# ----------------------------------------------------------------------------


_INSERT_SQL = """
INSERT INTO evidence (
    evidence_id, tier, outreach_origin, run_record,
    modality, sample_count_band, intent_goal,
    primary_metric_name, primary_metric_value,
    contributor_id, content_hash, created_at,
    synthetic_source, embedding_template_ver
)
VALUES (
    %(evidence_id)s, %(tier)s, %(outreach_origin)s, %(run_record)s,
    %(modality)s, %(sample_count_band)s, %(intent_goal)s,
    %(primary_metric_name)s, %(primary_metric_value)s,
    %(contributor_id)s, %(content_hash)s, %(created_at)s,
    %(synthetic_source)s, %(template_ver)s
)
"""

_SELECT_BY_ID_SQL = "SELECT run_record FROM evidence WHERE evidence_id = %s"


class PostgresEvidenceStore:
    """psycopg 3 async 기반 PostgreSQL 구현체."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, evidence: Evidence) -> None:
        params = _evidence_to_db_params(evidence)
        try:
            async with self._conn.cursor() as cur:
                await cur.execute(_INSERT_SQL, params)
            await self._conn.commit()
        except psycopg.errors.UniqueViolation as exc:
            await self._conn.rollback()
            raise EvidenceAlreadyExistsError(str(exc)) from exc

    async def get_by_id(self, evidence_id: str) -> Evidence | None:
        async with self._conn.cursor() as cur:
            await cur.execute(_SELECT_BY_ID_SQL, (evidence_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        run_record_json = row[0]
        if isinstance(run_record_json, str):
            run_record_json = json.loads(run_record_json)
        return Evidence.model_validate(run_record_json)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _evidence_to_db_params(evidence: Evidence) -> dict[str, Any]:
    """Pydantic Evidence → DB INSERT 파라미터 dict."""
    metrics = evidence.metrics
    primary_name, primary_value = _select_primary_metric(metrics)

    synthetic_json = (
        evidence.synthetic_source.model_dump(mode="json")
        if evidence.synthetic_source
        else None
    )

    return {
        "evidence_id": evidence.evidence_id,
        "tier": evidence.tier,
        "outreach_origin": evidence.outreach_origin,
        "run_record": json.dumps(evidence.model_dump(mode="json")),
        "modality": evidence.data_fingerprint.modality,
        "sample_count_band": evidence.data_fingerprint.sample_count_band,
        "intent_goal": evidence.intent.goal,
        "primary_metric_name": primary_name,
        "primary_metric_value": primary_value,
        "contributor_id": evidence.attribution.contributor_id,
        "content_hash": evidence.attribution.content_hash,
        "created_at": evidence.attribution.created_at,
        "synthetic_source": json.dumps(synthetic_json) if synthetic_json else None,
        "template_ver": "v1",
    }


def _select_primary_metric(metrics: dict[str, Any]) -> tuple[str | None, float | None]:
    """metrics dict에서 첫 numeric 항목을 primary로 선정. 표시 + filter용."""
    for name, value in metrics.items():
        if isinstance(value, int | float):
            return name, float(value)
    return None, None
