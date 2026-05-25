"""Protocol 추상화 단위 테스트 (rerank/listwise는 KR7 cleanup으로 제거)."""

from the_commons.llm.protocol import (
    EmbeddingProvider,
    LLMReranker,
    RankedCandidate,
)


class _FakeEmbedding:
    """Protocol 준수 fake — 인터페이스 호환성만 검증."""

    async def embed(self, text: str) -> list[float]:
        return [0.0, 1.0, 2.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0, 2.0] for _ in texts]


class _FakeReranker:
    """Protocol 준수 fake."""

    async def rerank(
        self, query: str, candidates: list[str], top_n: int = 5
    ) -> list[RankedCandidate]:
        return [RankedCandidate(index=0, score=1.0, reasoning="fake")]


def test_fake_embedding_is_protocol_compatible() -> None:
    """runtime_checkable Protocol — duck typing 검증."""
    assert isinstance(_FakeEmbedding(), EmbeddingProvider)


def test_fake_reranker_is_protocol_compatible() -> None:
    assert isinstance(_FakeReranker(), LLMReranker)
