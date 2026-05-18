"""infogain.posterior — Beta 사후 / 미분엔트로피 / 기대 정보이득 단위 테스트.

scipy 의존을 피하기 위해(서비스 경량 — minimal deps) 해석적 기준값으로 검증.
- Beta(1,1) = uniform → 미분엔트로피 = 0 (정확).
- Beta(2,2) → H = lnB(2,2) − (α−1)(ψα−ψ(α+β)) − (β−1)(ψβ−ψ(α+β))
            = ln(1/6) − 2·(ψ(2)−ψ(4)) ≈ -0.1250923 (well-known).
"""

import math

from the_commons.matchmaker.infogain.posterior import BetaPosterior


def test_uniform_beta_1_1_has_zero_differential_entropy() -> None:
    assert math.isclose(BetaPosterior(1.0, 1.0).entropy(), 0.0, abs_tol=1e-12)


def test_beta_2_2_entropy_matches_known_closed_form() -> None:
    # 알려진 Beta(2,2) 미분엔트로피 ≈ -0.12509237
    assert math.isclose(
        BetaPosterior(2.0, 2.0).entropy(), -0.12509237, abs_tol=1e-6
    )


def test_beta_5_3_entropy_matches_independent_formula() -> None:
    # 독립 계산: lnB(5,3) − (4)(ψ5−ψ8) − (2)(ψ3−ψ8)
    a, b = 5.0, 3.0
    lnb = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)

    def _dg(x: float) -> float:
        r = 0.0
        while x < 6.0:
            r -= 1.0 / x
            x += 1.0
        f = 1.0 / (x * x)
        return r + (
            math.log(x)
            - 0.5 / x
            + f
            * (
                -1.0 / 12.0
                + f * (1.0 / 120.0 + f * (-1.0 / 252.0 + f * (1.0 / 240.0)))
            )
        )

    expected = (
        lnb
        - (a - 1.0) * (_dg(a) - _dg(a + b))
        - (b - 1.0) * (_dg(b) - _dg(a + b))
    )
    assert math.isclose(BetaPosterior(a, b).entropy(), expected, rel_tol=1e-9)


def test_update_success_observation_raises_mean_lowers_entropy() -> None:
    base = BetaPosterior(2.0, 2.0)
    after = base.update([1.0, 1.0, 1.0])  # 성공 관측 3건
    assert after.mean() > base.mean()
    assert after.entropy() < base.entropy()


def test_update_failure_observations_lower_mean() -> None:
    base = BetaPosterior(2.0, 2.0)
    after = base.update([0.0, 0.0, 0.0])  # 음성(실패) 관측만
    assert after.mean() < base.mean()


def test_fractional_observation_splits_pseudo_count() -> None:
    # 정규화 점수 0.7 → 성공 0.7 / 실패 0.3 pseudo-count
    after = BetaPosterior(1.0, 1.0).update([0.7])
    assert math.isclose(after.alpha, 1.7, abs_tol=1e-12)
    assert math.isclose(after.beta, 1.3, abs_tol=1e-12)


def test_expected_info_gain_is_non_negative_for_any_posterior() -> None:
    # 사후평균을 예측분포로 쓰므로 상호정보 → 항상 ≥0 (경계 사후 포함).
    for a, b in (
        (2.0, 3.0),
        (0.01, 0.1),  # reviewer 반례: 외부 p였다면 음수
        (1.0, 1.0),
        (1e4, 1e4),
        (0.5, 50.0),
    ):
        assert BetaPosterior(a, b).expected_info_gain() >= -1e-9


def test_more_confident_posterior_has_lower_expected_info_gain() -> None:
    # 관측 많은(뾰족한) 사후는 추가 관측의 기대 정보이득이 작다.
    flat = BetaPosterior(2.0, 2.0)
    sharp = BetaPosterior(50.0, 50.0)
    assert sharp.expected_info_gain() < flat.expected_info_gain()


def test_update_empty_observations_is_identity() -> None:
    base = BetaPosterior(3.0, 4.0)
    after = base.update([])
    assert after.alpha == base.alpha
    assert after.beta == base.beta
