"""Retriever — in-memory cosine + cold start fallback."""

import pytest

from the_commons.matchmaker.retriever import (
    InMemoryVectorIndex,
    RetrievedHit,
    VectorIndex,
    cold_start_candidates,
    is_corpus_too_sparse,
)


@pytest.fixture
def index() -> InMemoryVectorIndex:
    return InMemoryVectorIndex()


def test_in_memory_index_is_protocol_compatible(index: InMemoryVectorIndex) -> None:
    assert isinstance(index, VectorIndex)


async def test_search_returns_topk_sorted_by_similarity(index: InMemoryVectorIndex) -> None:
    """가까운 vector가 위로 정렬."""
    index.add("ev-near", [1.0, 0.0, 0.0], tier="real")
    index.add("ev-mid", [0.5, 0.5, 0.0], tier="real")
    index.add("ev-far", [0.0, 0.0, 1.0], tier="real")

    hits = await index.search([1.0, 0.0, 0.0], top_k=3)

    assert [h.evidence_id for h in hits] == ["ev-near", "ev-mid", "ev-far"]
    assert hits[0].similarity > hits[1].similarity > hits[2].similarity


async def test_search_respects_top_k(index: InMemoryVectorIndex) -> None:
    """top_k=2면 결과 2개로 잘림."""
    for i in range(5):
        index.add(f"ev-{i}", [float(i), 0.0, 0.0], tier="real")
    hits = await index.search([1.0, 0.0, 0.0], top_k=2)
    assert len(hits) == 2


async def test_search_with_zero_vector_returns_zero_similarity(
    index: InMemoryVectorIndex,
) -> None:
    """영벡터는 cosine 0."""
    index.add("ev-x", [1.0, 0.0, 0.0], tier="real")
    hits = await index.search([0.0, 0.0, 0.0], top_k=1)
    assert hits[0].similarity == 0.0


async def test_search_with_different_dim_returns_zero_similarity(
    index: InMemoryVectorIndex,
) -> None:
    """차원 다른 vector는 cosine 0 (안전 fallback)."""
    index.add("ev-x", [1.0, 0.0, 0.0], tier="real")
    hits = await index.search([1.0, 0.0], top_k=1)
    assert hits[0].similarity == 0.0


def test_is_corpus_too_sparse_when_below_top_n() -> None:
    """recommend_top_n(기본 5)보다 적으면 sparse."""
    hits = [RetrievedHit(evidence_id=f"ev-{i}", similarity=0.5, tier="real") for i in range(3)]
    assert is_corpus_too_sparse(hits) is True


def test_is_corpus_not_sparse_when_at_or_above_top_n() -> None:
    """recommend_top_n 이상이면 sparse 아님."""
    hits = [RetrievedHit(evidence_id=f"ev-{i}", similarity=0.5, tier="real") for i in range(5)]
    assert is_corpus_too_sparse(hits) is False


def test_cold_start_tabular_returns_five_default_candidates() -> None:
    """tabular modality에는 5개 default 후보."""
    candidates = cold_start_candidates(modality="tabular", intent_goal="exploration")
    assert len(candidates) == 5
    recipe_ids = [c.recipe_id for c in candidates]
    assert "lightgbm" in recipe_ids
    assert "tabpfn" in recipe_ids


def test_cold_start_unknown_modality_returns_empty() -> None:
    """v0.1에선 tabular만 지원 — vision 등은 빈 list."""
    candidates = cold_start_candidates(modality="vision", intent_goal="exploration")
    assert candidates == []
