"""Google Gemini 기반 EmbeddingProvider 구현체.

GeminiEmbedding2Provider: Gemini Embedding 2 (1024-dim Matryoshka 축소). cost_meter에
token 사용량 자동 보고. rerank/prior LLM은 KR7 cleanup으로 제거됐다 — 추천은 LLM-free이고
로컬 임베딩 옵션은 llm/local_embedding.py(BGE-m3).
"""

from typing import Any

from google import genai
from google.genai import types as genai_types

from the_commons.llm.cost_meter import meter
from the_commons.settings import settings

CHAR_PER_TOKEN_ESTIMATE = 4
EMBEDDING_DIMENSION = 1024  # pgvector HNSW(<= 2000)에 맞는 Matryoshka 축소 차원


def _make_client() -> genai.Client:
    """Gemini Client lazy-init."""
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY 미설정. .env 또는 환경변수에 등록 필요")
    return genai.Client(api_key=settings.google_api_key)


def _as_vector(embedding_item: Any) -> list[float]:
    """SDK 응답 타입이 변할 수 있으니 vector 필드를 안전하게 추출."""
    if hasattr(embedding_item, "values"):
        return list(embedding_item.values)
    if isinstance(embedding_item, list):
        return embedding_item
    raise TypeError(f"unexpected embedding shape: {type(embedding_item)}")


class GeminiEmbedding2Provider:
    """Gemini Embedding 2 기반 EmbeddingProvider 구현체.

    native 차원은 3072이지만 pgvector HNSW의 2000-dim 제한과 storage 비용을 고려해
    output_dimensionality=1024로 Matryoshka 축소된 벡터를 사용(로컬 BGE-m3와 차원 일치).
    """

    def __init__(self, model: str | None = None, *, output_dim: int = EMBEDDING_DIMENSION) -> None:
        self._model = model or settings.gemini_embedding_model
        self._client = _make_client()
        self._output_dim = output_dim

    async def embed(self, text: str) -> list[float]:
        """단일 text → 임베딩 벡터."""
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """다수 text를 임베딩 (Gemini embed_content는 content 1회당 1 vector, sequential)."""
        config = genai_types.EmbedContentConfig(output_dimensionality=self._output_dim)
        vectors: list[list[float]] = []
        for t in texts:
            response = self._client.models.embed_content(
                model=self._model, contents=t, config=config
            )
            vectors.append(_as_vector(response.embeddings[0]))
            meter.record(
                model=self._model,
                operation="embedding",
                input_tokens=max(1, len(t) // CHAR_PER_TOKEN_ESTIMATE),
            )
        return vectors
