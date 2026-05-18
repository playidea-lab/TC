"""recipe별 Beta 사후분포 — 닫힌형 미분엔트로피·기대 정보이득.

분포족 = Beta 단일 고정 (DEC-003 / pre-mortem). min-max 정규화된 [0,1]
성공도를 Beta 평균으로 보고, 정규화 점수 x를 성공 x / 실패 (1-x)의
pseudo-count로 흡수한다. 음성·실패 evidence는 낮은 정규화 점수 →
β 가중으로 *구조적으로* 1급 (후처리 페널티가 아니다).

scipy 의존을 피한다 (FastAPI 서비스 경량 — minimal deps). betaln은
stdlib math.lgamma로, digamma는 점근급수 구현으로 닫힌형 계산.
요청별 일회성 fit·폐기 — stateless 정합.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _digamma(x: float) -> float:
    """ψ(x) 점근급수 근사. x>0에서 ~1e-10 정확도."""
    result = 0.0
    # x<6이면 재귀식으로 x를 6 이상으로 끌어올림
    while x < 6.0:
        result -= 1.0 / x
        x += 1.0
    f = 1.0 / (x * x)
    result += (
        math.log(x)
        - 0.5 / x
        + f
        * (
            -1.0 / 12.0
            + f * (1.0 / 120.0 + f * (-1.0 / 252.0 + f * (1.0 / 240.0)))
        )
    )
    return result


def _betaln(a: float, b: float) -> float:
    """ln B(a,b) = lnΓ(a)+lnΓ(b)−lnΓ(a+b)."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _beta_entropy(a: float, b: float) -> float:
    """Beta(a,b) 미분엔트로피 닫힌형.

    H = lnB(a,b) − (a−1)(ψa−ψ(a+b)) − (b−1)(ψb−ψ(a+b)).
    """
    psi_ab = _digamma(a + b)
    return (
        _betaln(a, b)
        - (a - 1.0) * (_digamma(a) - psi_ab)
        - (b - 1.0) * (_digamma(b) - psi_ab)
    )


@dataclass(frozen=True)
class BetaPosterior:
    """recipe 한 개의 Beta(α,β) 사후. 불변 — update는 새 인스턴스 반환."""

    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if self.alpha <= 0.0 or self.beta <= 0.0:
            raise ValueError(
                f"Beta 파라미터는 >0 이어야 함: alpha={self.alpha}, beta={self.beta}"
            )

    def mean(self) -> float:
        """사후 평균 α/(α+β) — recipe의 기대 성공도."""
        return self.alpha / (self.alpha + self.beta)

    def entropy(self) -> float:
        """현재 사후의 미분엔트로피 (불확실성)."""
        return _beta_entropy(self.alpha, self.beta)

    def update(self, observations: list[float]) -> BetaPosterior:
        """정규화 [0,1] 관측들을 pseudo-count로 흡수한 새 사후.

        s=Σx, f=Σ(1-x). post=Beta(α+s, β+f). 빈 리스트면 동일 사후.
        """
        if not observations:
            return self
        s = math.fsum(observations)
        f = math.fsum(1.0 - x for x in observations)
        return BetaPosterior(self.alpha + s, self.beta + f)

    def expected_info_gain(self) -> float:
        """이 recipe의 다음 관측 1건이 줄여줄 기대 엔트로피 (= 상호정보).

        다음 결과의 예측분포는 *반드시* 사후 예측확률 p=α/(α+β)이어야
        한다 (임의 외부 p를 쓰면 유효한 기대가 아니고 음수가 될 수 있다 —
        독립 수학 검증에서 확인된 함정).

          success(prob p) → Beta(α+1,β),  failure(prob 1−p) → Beta(α,β+1)
          E[posterior H] = p·H(α+1,β) + (1−p)·H(α,β+1)
          info_gain = H(현재) − E[posterior H]

        p=사후평균이면 이는 다음 관측과 θ의 상호정보 → 항상 ≥0.
        평평한(불확실한) 사후일수록 크다 → 덜 탐사된 recipe를 우선
        탐사하라는 active-learning 신호 (ID2 정합).
        """
        p = self.mean()
        current = self.entropy()
        h_success = _beta_entropy(self.alpha + 1.0, self.beta)
        h_failure = _beta_entropy(self.alpha, self.beta + 1.0)
        expected_post = p * h_success + (1.0 - p) * h_failure
        return current - expected_post
