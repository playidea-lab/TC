"""Stage 1 retrieve — query vector → top-K evidence_ids.

VectorIndex Protocol 추상화로 pgvector·in-memory 자유 교체.
cold start (corpus 너무 sparse) 시 heuristic fallback 발동.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import psycopg

from the_commons.settings import settings


@dataclass(frozen=True)
class RetrievedHit:
    """retrieve 결과 한 항목."""

    evidence_id: str
    similarity: float  # cosine similarity 0.0~1.0
    tier: str  # 'real' | 'synthetic'


@runtime_checkable
class VectorIndex(Protocol):
    """vector retrieve 인터페이스."""

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
    ) -> list[RetrievedHit]:
        """cosine similarity 상위 K개. deprecated=FALSE 인 evidence만."""
        ...


# ----------------------------------------------------------------------------
# In-memory (test)
# ----------------------------------------------------------------------------


class InMemoryVectorIndex:
    """test용 in-memory cosine search."""

    def __init__(self) -> None:
        self._items: list[tuple[str, list[float], str]] = []

    def add(self, evidence_id: str, vector: list[float], tier: str) -> None:
        self._items.append((evidence_id, vector, tier))

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
    ) -> list[RetrievedHit]:
        scored = [
            RetrievedHit(
                evidence_id=eid,
                similarity=_cosine(query_vector, vec),
                tier=tier,
            )
            for eid, vec, tier in self._items
        ]
        scored.sort(key=lambda h: h.similarity, reverse=True)
        return scored[:top_k]


def _cosine(a: list[float], b: list[float]) -> float:
    """길이 같은 두 벡터의 cosine similarity. 영벡터는 0."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ----------------------------------------------------------------------------
# PostgreSQL (pgvector)
# ----------------------------------------------------------------------------


_PGVECTOR_SEARCH_SQL = """
SELECT evidence_id, 1 - (embedding <=> %s::vector) AS similarity, tier
FROM evidence
WHERE embedding IS NOT NULL AND deprecated = FALSE
ORDER BY embedding <=> %s::vector
LIMIT %s
"""


class PgvectorVectorIndex:
    """pgvector cosine 검색. <=> 연산자가 cosine distance."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
    ) -> list[RetrievedHit]:
        async with self._conn.cursor() as cur:
            await cur.execute(_PGVECTOR_SEARCH_SQL, (query_vector, query_vector, top_k))
            rows = await cur.fetchall()
        return [
            RetrievedHit(evidence_id=row[0], similarity=float(row[1]), tier=row[2])
            for row in rows
        ]


# ----------------------------------------------------------------------------
# Cold start 휴리스틱 fallback
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class HeuristicCandidate:
    """corpus가 비었을 때 사용되는 일반 후보."""

    recipe_id: str
    description: str


# 매우 작은 catalog — v0.2엔 DB recipe table에서 로딩
_TABULAR_BINARY_FALLBACK: list[HeuristicCandidate] = [
    HeuristicCandidate(
        recipe_id="lightgbm",
        description="LightGBM (gradient boosting) — strong baseline on tabular binary",
    ),
    HeuristicCandidate(
        recipe_id="xgboost",
        description="XGBoost — competitive boosting alternative",
    ),
    HeuristicCandidate(
        recipe_id="tabpfn",
        description="TabPFN — strong on small tabular (<10k)",
    ),
    HeuristicCandidate(
        recipe_id="sklearn-rf",
        description="sklearn RandomForest — fast baseline",
    ),
    HeuristicCandidate(
        recipe_id="logistic-regression",
        description="Logistic Regression — interpretable baseline",
    ),
]


def cold_start_candidates(
    modality: str,
    intent_goal: str,  # noqa: ARG001 — 향후 분기 예정
    top_n: int = 5,
) -> list[HeuristicCandidate]:
    """corpus가 비었을 때 추천할 일반 후보. v0.1은 tabular만 지원."""
    if modality == "tabular":
        return _TABULAR_BINARY_FALLBACK[:top_n]
    return []


def is_corpus_too_sparse(hits: list[RetrievedHit]) -> bool:
    """retrieve 결과가 너무 적거나 비어있어 fallback이 필요한지 판단."""
    return len(hits) < settings.recommend_top_n
