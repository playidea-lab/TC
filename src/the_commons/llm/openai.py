"""OpenAI 기반 텍스트 생성 구현체 (PriorLLM / SynthesisLLM Protocol).

generation 부담을 Gemini에서 OpenAI로 분리 — Gemini 무료 quota(429
RESOURCE_EXHAUSTED) 회피용. synthesizer(within/novelty)와 infogain prior가
공유한다 (둘 다 `async complete(prompt) -> str` 시그니처).

embedding은 Anthropic처럼 OpenAI로 옮기지 않는다 — 옮기면 차원이 바뀌어 corpus
전체 re-embed가 필요하므로 v1에선 GeminiEmbedding2Provider 유지.

cost_meter에 사용량 보고 — 일일 cost ceiling이 OpenAI 호출도 포함하도록.
"""

from __future__ import annotations

import structlog
from openai import AsyncOpenAI

from the_commons.llm.cost_meter import meter
from the_commons.settings import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

CHAR_PER_TOKEN_ESTIMATE = 4


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // CHAR_PER_TOKEN_ESTIMATE)


class OpenAIChatLLM:
    """OpenAI chat completion 기반 텍스트 생성.

    PriorLLM(infogain Beta prior) + SynthesisLLM(next_config 합성) 양쪽 Protocol을
    동일 시그니처 `complete`로 만족한다. temperature=0으로 결정성 강화.
    """

    def __init__(self, model: str | None = None) -> None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 미설정. .env 또는 환경변수에 등록 필요"
            )
        self._model = model or settings.openai_model
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def complete(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = response.choices[0].message.content or ""

        usage = response.usage
        in_tokens = getattr(usage, "prompt_tokens", None) or _approx_tokens(prompt)
        out_tokens = getattr(usage, "completion_tokens", None) or _approx_tokens(text)
        meter.record(
            model=self._model,
            operation="prior",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )
        return text
