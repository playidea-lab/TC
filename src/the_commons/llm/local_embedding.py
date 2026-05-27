"""BGE-m3 로컬 임베딩 — LLM API·quota 없이 1024-dim dense 벡터.

TC를 LLM-free로 만드는 핵심(idea: tc-cumulative-knowledge). Gemini embedding(quota 429
병목, 5h re-embed가 막힌 원인)을 로컬 SentenceTransformer로 대체한다. BGE-m3 dense 차원
1024 = 기존 pgvector 컬럼과 일치 → 마이그레이션 불필요. cosine 검색 정합을 위해 정규화.

EmbeddingProvider 프로토콜(embed/embed_batch) 구현 — get_embedder가 이걸 주입하면 TC의
검색 경로에서 외부 LLM 의존이 사라진다.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

# BGE-m3 dense 차원 — 기존 Gemini Matryoshka 1024와 일치(컬럼 변경 불필요)
EMBEDDING_DIMENSION = 1024
DEFAULT_MODEL = "BAAI/bge-m3"


class LocalEmbeddingProvider:
    """BGE-m3 SentenceTransformer 로컬 임베딩 (EmbeddingProvider 프로토콜)."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None) -> None:
        # 무거운 import는 인스턴스 생성 시점으로 미룬다(모듈 import는 가볍게 유지)
        import torch
        from sentence_transformers import SentenceTransformer

        if device is None:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._model = SentenceTransformer(model_name, device=device)

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # encode는 동기(GPU/CPU bound) → executor로 이벤트 루프를 막지 않는다.
        # normalize_embeddings=True: cosine 검색(pgvector)과 정합하도록 L2 정규화.
        loop = asyncio.get_event_loop()
        vectors = await loop.run_in_executor(
            None, lambda: self._model.encode(texts, normalize_embeddings=True)
        )
        return [vector.tolist() for vector in vectors]


@lru_cache(maxsize=1)
def shared_local_embedder() -> LocalEmbeddingProvider:
    """프로세스당 1회만 로드되는 BGE-m3 임베더 — 모델 로드가 무거워 싱글톤."""
    return LocalEmbeddingProvider()
