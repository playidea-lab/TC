"""infogain.llm_prior — 저데이터 regime LLM Beta prior + RR6 graceful degrade."""


from the_commons.matchmaker.infogain.llm_prior import (
    WEAK_DEFAULT_PRIOR,
    llm_beta_prior,
    llm_beta_priors_batch,
)
from the_commons.matchmaker.infogain.posterior import BetaPosterior
from the_commons.settings import settings


class _RaisingLLM:
    """호출되면 예외 — '호출 안 됨' 검증 + 예외 degrade 검증용."""

    def __init__(self) -> None:
        self.called = False

    async def complete(self, prompt: str) -> str:
        self.called = True
        raise RuntimeError("LLM down")


class _FixedLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.called = False

    async def complete(self, prompt: str) -> str:
        self.called = True
        return self._text


async def test_real_count_at_threshold_skips_llm_returns_weak_default() -> None:
    llm = _RaisingLLM()
    a, b = await llm_beta_prior(
        "lightgbm", "ctx", real_count=settings.retirement_real_threshold, llm=llm
    )
    assert (a, b) == WEAK_DEFAULT_PRIOR
    assert llm.called is False  # threshold 이상 → LLM 미호출


async def test_real_count_above_threshold_skips_llm() -> None:
    llm = _RaisingLLM()
    a, b = await llm_beta_prior(
        "r", "ctx", real_count=settings.retirement_real_threshold + 5, llm=llm
    )
    assert (a, b) == WEAK_DEFAULT_PRIOR
    assert llm.called is False


async def test_llm_exception_degrades_to_weak_default(caplog) -> None:
    llm = _RaisingLLM()
    a, b = await llm_beta_prior("r", "ctx", real_count=0, llm=llm)
    assert llm.called is True  # 저데이터 → 호출 시도
    assert (a, b) == WEAK_DEFAULT_PRIOR  # 예외 → degrade (중단 없음)


async def test_valid_llm_response_parsed_and_within_clamp() -> None:
    llm = _FixedLLM('{"alpha": 2.0, "beta": 3.0}')
    a, b = await llm_beta_prior("r", "ctx", real_count=0, llm=llm)
    assert a > 0.0 and b > 0.0
    # 클램프 범위 내 + BetaPosterior가 받아들임
    BetaPosterior(a, b)


async def test_unparseable_response_degrades_to_weak_default() -> None:
    llm = _FixedLLM("그냥 횡설수설, 숫자 없음")
    a, b = await llm_beta_prior("r", "ctx", real_count=0, llm=llm)
    assert (a, b) == WEAK_DEFAULT_PRIOR


async def test_extreme_values_are_clamped_weak() -> None:
    # LLM이 과신(거대 α,β) → 약하게 클램프되어 likelihood가 곧 이김
    llm = _FixedLLM('{"alpha": 99999, "beta": 0.00001}')
    a, b = await llm_beta_prior("r", "ctx", real_count=0, llm=llm)
    assert 0.0 < a <= 10.0
    assert 0.0 < b <= 10.0


async def test_weak_default_is_uniform_prior() -> None:
    assert WEAK_DEFAULT_PRIOR == (1.0, 1.0)
    assert BetaPosterior(*WEAK_DEFAULT_PRIOR).mean() == 0.5


# ---------- 배치 prior (직렬 N회 → 1회) ----------


async def test_batch_prior_parses_multiple_recipes_in_one_call() -> None:
    llm = _FixedLLM(
        '{"rf": {"alpha": 2.0, "beta": 3.0}, "xgb": {"alpha": 1.5, "beta": 1.5}}'
    )
    out = await llm_beta_priors_batch(["rf", "xgb"], "ctx", llm=llm)
    assert set(out.keys()) == {"rf", "xgb"}
    assert all(a > 0.0 and b > 0.0 for a, b in out.values())
    assert llm.called is True  # 1회만 호출


async def test_batch_prior_empty_input_skips_llm() -> None:
    llm = _RaisingLLM()
    out = await llm_beta_priors_batch([], "ctx", llm=llm)
    assert out == {}
    assert llm.called is False  # 빈 입력 → LLM 미호출


async def test_batch_prior_missing_recipe_excluded_from_result() -> None:
    # 응답에 xgb 누락 → 결과에서 빠짐 (호출부가 weak default로 채움)
    llm = _FixedLLM('{"rf": {"alpha": 2.0, "beta": 2.0}}')
    out = await llm_beta_priors_batch(["rf", "xgb"], "ctx", llm=llm)
    assert "rf" in out
    assert "xgb" not in out


async def test_batch_prior_exception_degrades_to_empty() -> None:
    llm = _RaisingLLM()
    out = await llm_beta_priors_batch(["rf"], "ctx", llm=llm)
    assert out == {}  # 예외 → 빈 dict (RR6, 중단 없음)


async def test_batch_prior_clamps_extreme_values() -> None:
    llm = _FixedLLM('{"rf": {"alpha": 99999, "beta": 0.00001}}')
    out = await llm_beta_priors_batch(["rf"], "ctx", llm=llm)
    a, b = out["rf"]
    assert 0.0 < a <= 10.0
    assert 0.0 < b <= 10.0
