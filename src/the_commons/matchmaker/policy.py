"""ExplorationPolicy — ε-novelty mix over infogain의 분기 결정자.

매 /recommend 호출마다 deterministic RNG로 exploit/explore 분기를 결정한다.
seed = sha256(corpus_size, round_id, intent) — 같은 state·round는 같은 분기 (재현성).

cold_start 분기는 본 정책 단독 책임이 아니라 service layer에서 corpus sparsity
체크(`is_corpus_too_sparse`) 후 우회 처리한다. 이 모듈은 그 경우 호출되지 않는다.

Branch Literal에 "cold_start"가 포함된 이유는 동일 enum을 envelope.attribution.policy
.branch에 그대로 박기 위함 — policy 코드가 cold_start를 직접 반환하진 않지만
타입은 cold_start까지 허용한다.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Literal, Protocol

Branch = Literal["exploit", "explore", "cold_start"]


class ExplorationPolicy(Protocol):
    """ε-novelty mix 정책 인터페이스. v1엔 FixedEpsilonPolicy 1개만 있다.

    version 문자열은 envelope.attribution.policy.version에 그대로 박혀서 사후
    v1→v2 정책 비교 분석의 기준점이 된다.
    """

    version: str

    def choose_branch(
        self, *, corpus_size: int, round_id: str, intent: str
    ) -> Branch: ...


@dataclass(frozen=True)
class FixedEpsilonPolicy:
    """고정 ε ε-novelty mix. v1 기본 정책.

    eps=0이면 항상 exploit, eps=1이면 항상 explore. 1-ε 확률로 exploit, ε 확률로
    explore. RNG seed는 (corpus_size, round_id, intent)의 sha256으로 결정 — 같은
    상태·round는 같은 분기. PYTHONHASHSEED 의존 없음.
    """

    eps: float = 0.1
    version: str = "fixed_eps_v1"

    def choose_branch(
        self, *, corpus_size: int, round_id: str, intent: str
    ) -> Branch:
        # 경계값을 RNG 호출 없이 처리 — 부동소수점 비교 함정 회피
        if self.eps <= 0.0:
            return "exploit"
        if self.eps >= 1.0:
            return "explore"
        seed = _stable_seed(corpus_size, round_id, intent)
        rng = random.Random(seed)
        return "explore" if rng.random() < self.eps else "exploit"


def _stable_seed(corpus_size: int, round_id: str, intent: str) -> int:
    """PYTHONHASHSEED 영향을 받지 않는 결정적 seed. 64-bit로 truncate."""
    payload = f"{corpus_size}|{round_id}|{intent}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)
