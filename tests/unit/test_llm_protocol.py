"""Protocol 추상화 + listwise 응답 파싱 단위 테스트."""

import pytest

from the_commons.llm.gemini import (
    _build_listwise_prompt,
    _parse_listwise_response,
)
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
        self,
        query: str,
        candidates: list[str],
        top_n: int = 5,
    ) -> list[RankedCandidate]:
        return [RankedCandidate(index=0, score=1.0, reasoning="fake")]


def test_fake_embedding_is_protocol_compatible() -> None:
    """runtime_checkable Protocol — duck typing 검증."""
    fake = _FakeEmbedding()
    assert isinstance(fake, EmbeddingProvider)


def test_fake_reranker_is_protocol_compatible() -> None:
    fake = _FakeReranker()
    assert isinstance(fake, LLMReranker)


def test_listwise_prompt_includes_query_candidates_and_json_instruction() -> None:
    """prompt에 query, candidates, JSON 출력 지시가 모두 포함되어야 한다."""
    prompt = _build_listwise_prompt(
        query="tabular dataset 50k rows",
        candidates=["lightgbm", "xgboost", "tabpfn"],
        top_n=2,
    )
    assert "tabular dataset 50k rows" in prompt
    assert "[0] lightgbm" in prompt
    assert "[1] xgboost" in prompt
    assert "[2] tabpfn" in prompt
    assert "JSON" in prompt
    assert "exactly 2 objects" in prompt


def test_parse_listwise_response_extracts_valid_entries() -> None:
    """올바른 JSON 응답을 RankedCandidate list로 변환."""
    raw = (
        '[{"index": 1, "score": 0.91, "reasoning": "best AUC observed"},'
        ' {"index": 0, "score": 0.84, "reasoning": "fast baseline"}]'
    )
    result = _parse_listwise_response(raw, total_candidates=3, top_n=2)
    assert len(result) == 2
    assert result[0].index == 1
    assert result[0].score == pytest.approx(0.91)
    assert "AUC" in result[0].reasoning


def test_parse_listwise_response_strips_markdown_fence() -> None:
    """LLM이 ```json ... ``` fence로 감싸도 파싱 가능."""
    raw = '```json\n[{"index": 0, "score": 0.5, "reasoning": "ok"}]\n```'
    result = _parse_listwise_response(raw, total_candidates=1, top_n=1)
    assert len(result) == 1
    assert result[0].index == 0


def test_parse_listwise_response_with_invalid_json_returns_empty() -> None:
    """JSON 파싱 실패는 graceful degrade — 빈 list."""
    raw = "this is not JSON at all"
    result = _parse_listwise_response(raw, total_candidates=2, top_n=2)
    assert result == []


def test_parse_listwise_response_filters_out_of_range_indices() -> None:
    """잘못된 index는 무시 (candidate 범위 밖)."""
    raw = (
        '[{"index": 999, "score": 1.0, "reasoning": "invalid"},'
        ' {"index": 0, "score": 0.5, "reasoning": "valid"}]'
    )
    result = _parse_listwise_response(raw, total_candidates=2, top_n=5)
    assert len(result) == 1
    assert result[0].index == 0
