"""Google Gemini 기반 EmbeddingProvider + LLMReranker 구현체.

- GeminiEmbedding2Provider: Gemini Embedding 2 (text + multimodal-ready v0.2)
- GeminiFlash25Reranker:    Gemini Flash 2.5 listwise rerank (1M context)

cost_meter에 token 사용량 자동 보고. API 호출 실패는 상위에서 처리 (재시도/circuit
breaker는 plan 단계 결정).
"""

import json
from typing import Any

import structlog
from google import genai
from google.genai import types as genai_types

from the_commons.llm.cost_meter import meter
from the_commons.llm.protocol import RankedCandidate
from the_commons.settings import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _make_client() -> genai.Client:
    """Gemini Client lazy-init."""
    if not settings.google_api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY 미설정. .env 또는 환경변수에 등록 필요"
        )
    return genai.Client(api_key=settings.google_api_key)


EMBEDDING_DIMENSION = 1024  # pgvector HNSW(<= 2000)에 맞는 Matryoshka 축소 차원


class GeminiEmbedding2Provider:
    """Gemini Embedding 2 기반 EmbeddingProvider 구현체.

    native 차원은 3072이지만 pgvector HNSW의 2000-dim 제한과 storage 비용을
    고려해 output_dimensionality=1024로 Matryoshka 축소된 벡터를 사용.
    """

    def __init__(
        self, model: str | None = None, *, output_dim: int = EMBEDDING_DIMENSION
    ) -> None:
        self._model = model or settings.gemini_embedding_model
        self._client = _make_client()
        self._output_dim = output_dim

    async def embed(self, text: str) -> list[float]:
        """단일 text → 임베딩 벡터."""
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """다수 text를 임베딩. Gemini embed_content는 단일 content 1회당 1 vector만
        반환하므로 sequential N회 호출로 처리.
        """
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


class GeminiFlash25Reranker:
    """Gemini Flash 2.5 listwise rerank 구현체."""

    def __init__(self, model: str | None = None) -> None:
        self._model = model or settings.gemini_reranker_model
        self._client = _make_client()

    async def rerank(
        self,
        query: str,
        candidates: list[str],
        top_n: int = 5,
    ) -> list[RankedCandidate]:
        """listwise 1회 호출로 top-N rerank."""
        prompt = _build_listwise_prompt(query, candidates, top_n)

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        text = response.text or ""
        ranked = _parse_listwise_response(text, len(candidates), top_n)

        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", _approx_tokens(prompt))
        out_tokens = getattr(usage, "candidates_token_count", _approx_tokens(text))
        meter.record(
            model=self._model,
            operation="rerank",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )
        return ranked


class GeminiPriorLLM:
    """저데이터 regime Beta prior 추출용 텍스트 생성 (PriorLLM 구현).

    GeminiFlash25Reranker와 동일하게 meter.record로 비용을 보고한다 —
    일일 cost ceiling이 prior 호출도 포함하도록 (계측 누락 = ceiling 우회).
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model or settings.gemini_reranker_model
        self._client = _make_client()

    async def complete(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        text = response.text or ""

        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", _approx_tokens(prompt))
        out_tokens = getattr(usage, "candidates_token_count", _approx_tokens(text))
        meter.record(
            model=self._model,
            operation="prior",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )
        return text


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

CHAR_PER_TOKEN_ESTIMATE = 4


def _approx_tokens(text: str) -> int:
    """간단한 token 추정 — usage metadata 없는 경우 fallback."""
    return max(1, len(text) // CHAR_PER_TOKEN_ESTIMATE)


def _as_vector(embedding_item: Any) -> list[float]:
    """SDK 응답 타입이 변할 수 있으니 vector 필드를 안전하게 추출."""
    if hasattr(embedding_item, "values"):
        return list(embedding_item.values)
    if isinstance(embedding_item, list):
        return embedding_item
    raise TypeError(f"unexpected embedding shape: {type(embedding_item)}")


def _build_listwise_prompt(query: str, candidates: list[str], top_n: int) -> str:
    """listwise rerank prompt 작성. JSON 출력 강제."""
    lines = [
        "You are a match-maker for ML experiments. Given a query (a problem + "
        "hardware + intent) and candidate evidence records, rank candidates by how "
        "well each recipe would help the query.",
        "",
        f"QUERY:\n{query}",
        "",
        "CANDIDATES:",
    ]
    for i, c in enumerate(candidates):
        lines.append(f"[{i}] {c}")
    lines += [
        "",
        f"Return strictly valid JSON: a list of exactly {top_n} objects, sorted by "
        "score descending. Each object: "
        '{"index": <int>, "score": <float 0-1>, "reasoning": <1-2 short sentences>}.',
        "Do not include any commentary outside the JSON array.",
    ]
    return "\n".join(lines)


def _parse_listwise_response(
    raw_text: str, total_candidates: int, top_n: int
) -> list[RankedCandidate]:
    """LLM 응답 텍스트에서 JSON 파싱. 부분 실패 시 graceful degrade."""
    text = raw_text.strip()
    # 응답에 ```json fence가 있을 수 있으니 제거
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "rerank_response_parse_failed",
            raw_preview=raw_text[:120],
            fallback="empty_list",
        )
        return []

    if not isinstance(parsed, list):
        return []

    result: list[RankedCandidate] = []
    for item in parsed[:top_n]:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int) or not 0 <= idx < total_candidates:
            continue
        result.append(
            RankedCandidate(
                index=idx,
                score=float(item.get("score", 0.0)),
                reasoning=str(item.get("reasoning", "")),
            )
        )
    return result
