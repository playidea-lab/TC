"""LLM 컴포넌트 Protocol.

EmbeddingProvider와 LLMReranker는 vendor 중립적인 인터페이스.
구현체는 Gemini, DeepSeek, 로컬 모델 등 자유 교체 가능.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RankedCandidate(BaseModel):
    """rerank 결과 한 항목."""

    index: int = Field(description="원본 candidate list에서의 위치 (0-based)")
    score: float = Field(description="0.0~1.0 정규화 점수 (높을수록 query와 정합)")
    reasoning: str = Field(description="LLM이 생성한 추천 근거 (1~2 문장)")


@runtime_checkable
class EmbeddingProvider(Protocol):
    """text → embedding vector 변환 인터페이스.

    구현체는 단일 text와 batch 호출을 모두 지원해야 한다.
    """

    async def embed(self, text: str) -> list[float]:
        """단일 text를 임베딩 벡터로 변환."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """다수 text를 한 번에 임베딩 — 호출 절감용."""
        ...


@runtime_checkable
class LLMReranker(Protocol):
    """retrieve된 top-K candidates를 listwise로 rerank하는 인터페이스.

    1회 LLM 호출로 K개 후보를 비교 reasoning한 뒤 top-N을 반환한다.
    """

    async def rerank(
        self,
        query: str,
        candidates: list[str],
        top_n: int = 5,
    ) -> list[RankedCandidate]:
        """listwise rerank. 결과는 score 내림차순으로 정렬된 RankedCandidate 리스트."""
        ...
