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

    async def update_embedding(
        self, evidence_id: str, embedding: list[float]
    ) -> None:
        """vector embedding 저장. ingest 직후 또는 re-embed batch에서 호출."""
        ...

    async def list_active_synthetics_in_bucket(
        self,
        *,
        modality: str,
        sample_count_band: str,
        intent_goal: str,
    ) -> list[Evidence]:
        """같은 bucket의 active(deprecated=FALSE) synthetic evidence 조회.

        ingest 후 promote/contradict 평가용.
        """
        ...

    async def count_real_in_bucket(
        self,
        *,
        modality: str,
        sample_count_band: str,
        intent_goal: str,
    ) -> int:
        """같은 bucket의 real evidence 개수. retirement 트리거 판정용."""
        ...

    async def mark_deprecated(self, evidence_id: str, *, reason: str) -> None:
        """L3 visibility 플래그 ON — 추천 corpus에서 제외 (record는 보존)."""
        ...

    async def list_evidence(
        self,
        *,
        tier: str | None = None,
        modality: str | None = None,
        sample_count_band: str | None = None,
        intent_goal: str | None = None,
        contributor_id: str | None = None,
        deprecated: bool | None = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Evidence], int]:
        """필터 조건으로 evidence 검색. 반환: (해당 페이지, 전체 매칭 카운트)."""
        ...


# ----------------------------------------------------------------------------
# In-memory (test)
# ----------------------------------------------------------------------------


class InMemoryEvidenceStore:
    """단위 테스트용 in-memory 구현체. 같은 schema 제약 (id/hash unique)을 적용."""

    def __init__(self) -> None:
        self._by_id: dict[str, Evidence] = {}
        self._hashes: set[str] = set()
        self._deprecated: set[str] = set()

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

    async def update_embedding(
        self, evidence_id: str, embedding: list[float]
    ) -> None:
        # InMemory는 별도 VectorIndex를 사용 (matchmaker.retriever.InMemoryVectorIndex).
        # 여기선 silent no-op — 통합 test에서 두 store를 함께 시드.
        _ = (evidence_id, embedding)

    async def list_active_synthetics_in_bucket(
        self,
        *,
        modality: str,
        sample_count_band: str,
        intent_goal: str,
    ) -> list[Evidence]:
        return [
            ev
            for ev in self._by_id.values()
            if ev.tier == "synthetic"
            and ev.evidence_id not in self._deprecated
            and ev.data_fingerprint.modality == modality
            and ev.data_fingerprint.sample_count_band == sample_count_band
            and ev.intent.goal == intent_goal
        ]

    async def count_real_in_bucket(
        self,
        *,
        modality: str,
        sample_count_band: str,
        intent_goal: str,
    ) -> int:
        return sum(
            1
            for ev in self._by_id.values()
            if ev.tier == "real"
            and ev.data_fingerprint.modality == modality
            and ev.data_fingerprint.sample_count_band == sample_count_band
            and ev.intent.goal == intent_goal
        )

    async def mark_deprecated(self, evidence_id: str, *, reason: str) -> None:
        if evidence_id not in self._by_id:
            return
        self._deprecated.add(evidence_id)
        _ = reason  # InMemory엔 audit log 별도 — RetirementBackend가 처리

    async def list_evidence(
        self,
        *,
        tier: str | None = None,
        modality: str | None = None,
        sample_count_band: str | None = None,
        intent_goal: str | None = None,
        contributor_id: str | None = None,
        deprecated: bool | None = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Evidence], int]:
        def _matches(ev: Evidence) -> bool:
            if tier is not None and ev.tier != tier:
                return False
            if modality is not None and ev.data_fingerprint.modality != modality:
                return False
            if (
                sample_count_band is not None
                and ev.data_fingerprint.sample_count_band != sample_count_band
            ):
                return False
            if intent_goal is not None and ev.intent.goal != intent_goal:
                return False
            if (
                contributor_id is not None
                and ev.attribution.contributor_id != contributor_id
            ):
                return False
            is_deprecated = ev.evidence_id in self._deprecated
            return not (deprecated is not None and is_deprecated != deprecated)

        matched = [ev for ev in self._by_id.values() if _matches(ev)]
        total = len(matched)
        page = matched[offset : offset + limit]
        return page, total


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

_LIST_ACTIVE_SYNTHETICS_SQL = """
SELECT run_record
FROM evidence
WHERE tier = 'synthetic'
  AND deprecated = FALSE
  AND modality = %s
  AND sample_count_band = %s
  AND intent_goal = %s
"""

_COUNT_REAL_SQL = """
SELECT COUNT(*) FROM evidence
WHERE tier = 'real'
  AND modality = %s
  AND sample_count_band = %s
  AND intent_goal = %s
"""

_MARK_DEPRECATED_SQL = """
UPDATE evidence
SET deprecated = TRUE, deprecated_reason = %s, deprecated_at = NOW()
WHERE evidence_id = %s AND deprecated = FALSE
"""

_UPDATE_EMBEDDING_SQL = """
UPDATE evidence SET embedding = %s::vector WHERE evidence_id = %s
"""

# evidence 검색 — 동적 WHERE은 _build_list_query로 조립
_LIST_BASE_SELECT = "SELECT run_record FROM evidence"
_LIST_BASE_COUNT = "SELECT COUNT(*) FROM evidence"


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
        return _row_to_evidence(row[0])

    async def list_active_synthetics_in_bucket(
        self,
        *,
        modality: str,
        sample_count_band: str,
        intent_goal: str,
    ) -> list[Evidence]:
        async with self._conn.cursor() as cur:
            await cur.execute(
                _LIST_ACTIVE_SYNTHETICS_SQL,
                (modality, sample_count_band, intent_goal),
            )
            rows = await cur.fetchall()
        return [_row_to_evidence(row[0]) for row in rows]

    async def count_real_in_bucket(
        self,
        *,
        modality: str,
        sample_count_band: str,
        intent_goal: str,
    ) -> int:
        async with self._conn.cursor() as cur:
            await cur.execute(
                _COUNT_REAL_SQL, (modality, sample_count_band, intent_goal)
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def mark_deprecated(self, evidence_id: str, *, reason: str) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(_MARK_DEPRECATED_SQL, (reason, evidence_id))
        await self._conn.commit()

    async def update_embedding(
        self, evidence_id: str, embedding: list[float]
    ) -> None:
        # list → pgvector literal 직접 변환 (psycopg list adapter 우회).
        # pgvector가 '[1.0,2.0,...]' 텍스트를 vector로 캐스팅.
        literal = "[" + ",".join(repr(float(v)) for v in embedding) + "]"
        async with self._conn.cursor() as cur:
            await cur.execute(_UPDATE_EMBEDDING_SQL, (literal, evidence_id))
        await self._conn.commit()

    async def list_evidence(
        self,
        *,
        tier: str | None = None,
        modality: str | None = None,
        sample_count_band: str | None = None,
        intent_goal: str | None = None,
        contributor_id: str | None = None,
        deprecated: bool | None = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Evidence], int]:
        where_sql, params = _build_list_where(
            tier=tier,
            modality=modality,
            sample_count_band=sample_count_band,
            intent_goal=intent_goal,
            contributor_id=contributor_id,
            deprecated=deprecated,
        )
        select_sql = (
            f"{_LIST_BASE_SELECT} {where_sql} "
            "ORDER BY created_at DESC LIMIT %s OFFSET %s"
        )
        count_sql = f"{_LIST_BASE_COUNT} {where_sql}"

        async with self._conn.cursor() as cur:
            await cur.execute(select_sql, (*params, limit, offset))
            rows = await cur.fetchall()
            await cur.execute(count_sql, params)
            count_row = await cur.fetchone()

        evidences = [_row_to_evidence(row[0]) for row in rows]
        total = int(count_row[0]) if count_row else 0
        return evidences, total


def _build_list_where(
    *,
    tier: str | None,
    modality: str | None,
    sample_count_band: str | None,
    intent_goal: str | None,
    contributor_id: str | None,
    deprecated: bool | None,
) -> tuple[str, tuple[Any, ...]]:
    """필터 dict → (WHERE clause, params tuple). 비어있으면 빈 WHERE."""
    clauses: list[str] = []
    params: list[Any] = []

    pairs = [
        ("tier", tier),
        ("modality", modality),
        ("sample_count_band", sample_count_band),
        ("intent_goal", intent_goal),
        ("contributor_id", contributor_id),
    ]
    for column, value in pairs:
        if value is not None:
            clauses.append(f"{column} = %s")
            params.append(value)

    if deprecated is not None:
        clauses.append("deprecated = %s")
        params.append(deprecated)

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, tuple(params)


def _row_to_evidence(run_record_json: Any) -> Evidence:
    """JSONB row → Evidence."""
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
