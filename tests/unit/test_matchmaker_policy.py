"""ExplorationPolicy 단위 테스트 — ε-novelty mix over infogain의 분기 결정자.

핵심 계약:
- 결정성: 같은 (corpus_size, round_id, intent)는 항상 같은 branch 반환.
- ε 정확성: 1000번 sampling 시 explore 비율이 ε ± tolerance.
- 경계: ε=0.0 → 항상 exploit, ε=1.0 → 항상 explore.
- version 마커: envelope.attribution.policy로 박힐 식별자가 안정적.
"""

from __future__ import annotations

from the_commons.matchmaker.policy import (
    Branch,
    ExplorationPolicy,
    FixedEpsilonPolicy,
)


def test_fixed_epsilon_policy_is_deterministic_for_same_inputs() -> None:
    """같은 (corpus_size, round_id, intent) 입력은 매번 같은 branch 반환."""
    p: ExplorationPolicy = FixedEpsilonPolicy(eps=0.1)
    a = p.choose_branch(corpus_size=12, round_id="round-007", intent="MNIST acc 올리기")
    b = p.choose_branch(corpus_size=12, round_id="round-007", intent="MNIST acc 올리기")
    c = p.choose_branch(corpus_size=12, round_id="round-007", intent="MNIST acc 올리기")
    assert a == b == c


def test_fixed_epsilon_policy_different_round_can_differ() -> None:
    """round_id가 바뀌면 branch가 갈릴 수 있어야 한다 (모두 같은 값이면 RNG 미동작)."""
    p = FixedEpsilonPolicy(eps=0.1)
    branches = {
        p.choose_branch(corpus_size=10, round_id=f"round-{i:04d}", intent="intent-x")
        for i in range(500)
    }
    # exploit/explore 둘 다 한 번씩은 나와야 결정성 ≠ 고정 분기.
    assert {"exploit", "explore"}.issubset(branches)


def test_eps_zero_always_exploit() -> None:
    """ε=0이면 어떤 입력에서도 exploit 분기만 나와야 한다."""
    p = FixedEpsilonPolicy(eps=0.0)
    for i in range(200):
        b = p.choose_branch(
            corpus_size=10, round_id=f"r-{i}", intent=f"i-{i}"
        )
        assert b == "exploit", f"eps=0인데 explore가 발생: round=r-{i}"


def test_eps_one_always_explore() -> None:
    """ε=1.0이면 어떤 입력에서도 explore 분기만 나와야 한다."""
    p = FixedEpsilonPolicy(eps=1.0)
    for i in range(200):
        b = p.choose_branch(
            corpus_size=10, round_id=f"r-{i}", intent=f"i-{i}"
        )
        assert b == "explore", f"eps=1인데 exploit가 발생: round=r-{i}"


def test_eps_zero_one_ratio_within_tolerance() -> None:
    """ε=0.1로 1000회 sampling — explore 비율이 0.1 ± 0.05 안에 들어와야 한다.

    deterministic hash 기반이라 통계적 검정이 아닌 분포 확인. tolerance는
    sample size에 비해 충분히 느슨하게 — 0.05는 신뢰구간이 아니라 sanity bound.
    """
    p = FixedEpsilonPolicy(eps=0.1)
    n = 1000
    explore_count = sum(
        1
        for i in range(n)
        if p.choose_branch(
            corpus_size=i % 50,
            round_id=f"r-{i:06d}",
            intent=f"intent-{i % 7}",
        )
        == "explore"
    )
    ratio = explore_count / n
    assert 0.05 <= ratio <= 0.15, f"explore 비율={ratio:.3f} 기대 0.1 ± 0.05"


def test_policy_version_marker_stable() -> None:
    """version 마커는 v1→v2 사후 분석용 식별자. FixedEpsilonPolicy면 항상 같은 문자열."""
    p1 = FixedEpsilonPolicy(eps=0.1)
    p2 = FixedEpsilonPolicy(eps=0.5)
    # eps가 달라도 정책 family는 같으므로 version 문자열 안에 family 식별자가 있어야.
    assert "fixed" in p1.version
    assert p1.version == p2.version or p1.version.startswith(p2.version.split("_")[0])


def test_branch_literal_values() -> None:
    """Branch는 정의된 세 값만 가져야 한다."""
    allowed: set[Branch] = {"exploit", "explore", "cold_start"}
    p = FixedEpsilonPolicy(eps=0.3)
    for i in range(100):
        b = p.choose_branch(corpus_size=i, round_id=f"r-{i}", intent="x")
        assert b in allowed
