"""GeminiPriorLLM — prior 호출이 cost_meter에 계측되는지 검증.

계측 누락은 일일 cost ceiling 우회를 의미한다 (서비스 가용성 차단 사유).
실 Gemini 호출 없이 client를 monkeypatch.
"""

import the_commons.llm.gemini as gemini_mod
from the_commons.llm.cost_meter import meter
from the_commons.llm.gemini import GeminiPriorLLM


class _FakeResponse:
    text = '{"alpha": 1.0, "beta": 1.0}'

    class _Usage:
        prompt_token_count = 120
        candidates_token_count = 30

    usage_metadata = _Usage()


class _FakeModels:
    def generate_content(self, *, model: str, contents: str):  # noqa: ANN001
        return _FakeResponse()


class _FakeClient:
    models = _FakeModels()


async def test_prior_call_is_metered(monkeypatch) -> None:
    monkeypatch.setattr(gemini_mod, "_make_client", lambda: _FakeClient())

    before = meter.today_total_usd()
    llm = GeminiPriorLLM()
    text = await llm.complete("prompt")

    assert text == '{"alpha": 1.0, "beta": 1.0}'
    # 계측됨 — 일일 누적 비용이 증가 (ceiling이 prior 호출 포함)
    assert meter.today_total_usd() > before


async def test_empty_response_text_is_safe(monkeypatch) -> None:
    class _EmptyResp:
        text = None
        usage_metadata = None

    class _M:
        def generate_content(self, *, model, contents):  # noqa: ANN001
            return _EmptyResp()

    class _C:
        models = _M()

    monkeypatch.setattr(gemini_mod, "_make_client", lambda: _C())
    out = await GeminiPriorLLM().complete("p")
    assert out == ""  # None → "" (llm_prior가 RR6로 degrade)
