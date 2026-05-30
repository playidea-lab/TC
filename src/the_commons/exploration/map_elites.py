"""explore-loop v2 — 결정론적 MAP-Elites/QD 컨트롤러.

산문 알고리즘(에이전트 즉흥 판단)을 **결정론 코드**로 흡수한다(idea: explore-loop-qd-rigor,
EARS RE1~RE9). SKILL.md는 `controller.step()`이 반환한 행동을 실행하고 `controller.report()`로
결과를 되돌리는 얇은 오케스트레이터가 된다.

핵심 책임:
  - RE1 BD 격자: archive 키 = (task, cap_bin, loc_bin). recipe는 genotype 정체로 셀 elite에 부착.
  - RE2 객관 binning: genotype→(cap_bin, loc_bin)은 주입된 BinRule(profile 규칙)로 결정.
  - RE3 풀 컨트롤러: select·place·adaptive-sampling·dedup·stop을 seed 고정으로 결정론 실행.
  - RE4 selection: 채운 셀 uniform 랜덤.
  - RE6 adaptive sampling: k=1 기본, 경계/의심 셀만 재평가 escalate.
  - RE7 분산인지 placement: 신규가 효과크기>noise로 능가할 때만 elite 교체(lucky-swap 차단).
  - RE8 universal=가설검정: 추상축 따라 ≥2 recipe 동일방향∧효과크기>noise → 보편 *가설*.
  - RE9 재현성: 같은 seed·budget에서 결정 완전 재현.

변이(mutation) 실행은 SKILL.md/에이전트 몫이다 — 컨트롤러는 "무엇을 평가할지"를 결정만 하고,
within 섭동값 생성과 cross recipe 저술은 호출자가 채운다(P0는 합성 harness가 대신).
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, Optional

# ----------------------------------------------------------------------------
# 정책 상수 — 효과크기/샘플 임계 (Cohen's d 관례 + 비싼 eval 레짐 보수값)
# ----------------------------------------------------------------------------

MIN_SAMPLES_FOR_TEST = 2          # 분산 추정 최소 표본 (미만이면 재평가)
EFFECT_REPLACE = 0.8              # elite 교체 효과크기 임계 (large effect)
EFFECT_BOUNDARY = 0.5             # 경계 판정 임계 (이하면 의심→재평가)
REEVAL_CAP = 4                    # 경계 셀 재평가 상한 (비용 + 0분산 무한 방지)
MAX_SAMPLES_PER_CELL = 10         # 절대 상한 (안전망)
EFFECT_UNIVERSAL = 0.8            # 축 추세 방향 판정 효과크기 임계
MAX_DEEPEN_GUARD = 6              # exploit 내 미tried 후보 탐색 시도 상한


# ----------------------------------------------------------------------------
# 자료구조
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Genotype:
    """해의 정체(identity). recipe + 정렬된 config 튜플(해시·dedup 가능)."""

    recipe: str
    config: tuple[tuple[str, float], ...]

    @staticmethod
    def of(recipe: str, config: dict[str, float]) -> "Genotype":
        return Genotype(recipe, tuple(sorted(config.items())))

    def as_dict(self) -> dict[str, float]:
        return dict(self.config)


@dataclass
class Cell:
    """BD 격자의 한 칸. elite genotype과 그 시드별 fitness 표본을 보관."""

    descriptor: tuple[int, int]
    elite: Optional[Genotype] = None
    samples: list[float] = field(default_factory=list)
    # 도전자: 아직 elite를 못 이겼지만 경계라 재평가 대상인 genotype들
    challenger: Optional[Genotype] = None
    challenger_samples: list[float] = field(default_factory=list)
    evals: int = 0                # 누적 평가 횟수 — 매 평가 유니크 seed 보장(reeval 분산)

    def elite_mean(self) -> float:
        return statistics.fmean(self.samples) if self.samples else float("-inf")


@dataclass
class Action:
    """컨트롤러가 호출자에게 지시하는 다음 평가 행동."""

    kind: str                      # exploit_within | explore_tier1 | explore_tier2 | reeval | stop
    task: str = ""
    genotype: Optional[Genotype] = None
    descriptor: tuple[int, int] = (-1, -1)
    seed: int = 0
    target: str = "elite"          # reeval 대상: elite | challenger
    reason: str = ""


# BinRule: genotype → (cap_bin, loc_bin). profile이 제공(RE2). P0는 합성 규칙 주입.
BinRule = Callable[[Genotype], tuple[int, int]]


# ----------------------------------------------------------------------------
# 통계 유틸
# ----------------------------------------------------------------------------


def cohen_d(a: list[float], b: list[float]) -> float:
    """두 표본의 표준화 평균차(Cohen's d). pooled SD 사용. 0분산이면 부호만."""
    na, nb = len(a), len(b)
    if na < MIN_SAMPLES_FOR_TEST or nb < MIN_SAMPLES_FOR_TEST:
        return 0.0
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    pooled = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
    if pooled <= 0:
        return math.copysign(EFFECT_REPLACE + 1.0, ma - mb) if ma != mb else 0.0
    return (mb - ma) / math.sqrt(pooled)


# ----------------------------------------------------------------------------
# 컨트롤러
# ----------------------------------------------------------------------------


@dataclass
class ControllerConfig:
    epsilon: float = 0.3
    budget: int = 40
    seed_base: int = 0
    max_tier2: int = 8               # coverage 소진 후 새 recipe 저술 위임 상한(무한 위임 방지)


class MapElitesController:
    """결정론적 QD 컨트롤러. step()→행동, report()→archive 갱신."""

    def __init__(
        self,
        config: ControllerConfig,
        bin_rule: BinRule,
        tasks: list[str],
        candidate_pool: dict[str, list[Genotype]],
        mutate_fn: Optional[Callable[[Genotype], Genotype]] = None,
    ) -> None:
        # candidate_pool[task] = 그 task에서 평가 가능한 genotype 후보(Tier1 미사용 recipe 포함)
        # mutate_fn = within-recipe 섭동 축 지정(RE5). profile/호출자가 제공.
        #   미지정 시 첫 수치 키 심화(도메인 무관 기본값).
        self.cfg = config
        self.bin_rule = bin_rule
        self.tasks = tasks
        self.pool = candidate_pool
        self.mutate_fn = mutate_fn or self._default_mutate
        self.archive: dict[tuple[str, int, int], Cell] = {}
        self.tried: set[tuple[str, Genotype]] = set()
        self.reeval_queue: list[Action] = []
        self.universals: list[dict] = []
        self.round = 0
        self.rng = random.Random(config.seed_base)
        self.tier2_count = 0                       # Tier2(새 recipe 저술) 위임 누적 — max_tier2 cap

    # -- 공개 API ----------------------------------------------------------

    def step(self) -> Action:
        """다음 평가 행동을 결정론적으로 선택한다."""
        if self.reeval_queue:                       # RE6: 재평가 최우선
            return self.reeval_queue.pop(0)
        if self.round >= self.cfg.budget or self.universals:
            return Action(kind="stop", reason=self._stop_reason())
        self.round += 1
        coin = self.rng.random()
        # ε에 따라 explore/exploit 우선순위. 한쪽이 후보 없으면(None) 다른 쪽 시도.
        order = (self._explore, self._exploit) if coin < self.cfg.epsilon \
            else (self._exploit, self._explore)
        for fn in order:
            act = fn()
            if act is not None:
                return act
        # implemented 격자 소진 — Tier2: 에이전트(LLM)에게 새 recipe 저술 위임(SKILL §2c)
        tier2 = self._tier2()
        if tier2 is not None:
            return tier2
        return Action(kind="stop", reason="coverage exhausted (implemented recipes + tier2 cap)")

    def report(self, action: Action, fitness: float) -> None:
        """평가 결과를 archive에 반영(분산인지 placement) 후 보편 가설 갱신."""
        if action.genotype is None:
            return
        self.tried.add((action.task, action.genotype))
        key = (action.task, *action.descriptor)
        cell = self.archive.setdefault(key, Cell(descriptor=action.descriptor))
        self._place(cell, action, fitness)
        self._detect_universals()

    # -- 분기 선택 ---------------------------------------------------------

    def _explore(self) -> Optional[Action]:
        """빈/저밀도 bin을 채울 미사용 genotype 선택(Tier1). 없으면 None(에이전트 Tier2+)."""
        task = self.tasks[self.round % len(self.tasks)]
        untried = [g for g in self.pool.get(task, []) if (task, g) not in self.tried]
        if not untried:
            return None
        cov = {self.bin_rule(g): self.archive.get((task, *self.bin_rule(g))) for g in untried}
        # 아직 비어있는 bin으로 가는 genotype 우선(coverage 구동)
        empty = [g for g in untried if cov[self.bin_rule(g)] is None]
        pick = self._det_choice(empty or untried)
        return Action(kind="explore_tier1", task=task, genotype=pick,
                      descriptor=self.bin_rule(pick), seed=self._seed(task, pick),
                      reason="coverage: fill empty bin" if empty else "coverage: untried")

    def _exploit(self) -> Optional[Action]:
        """채운 셀을 uniform 선택(RE4) → capacity 심화. 중복/상한이면 다른 셀, 다 막히면 None."""
        filled = sorted(k for k, c in self.archive.items() if c.elite is not None)
        if not filled:
            return self._cold_start()
        start = self.rng.randrange(len(filled))        # uniform 시작점
        for i in range(len(filled)):
            key = filled[(start + i) % len(filled)]
            task, cell = key[0], self.archive[key]
            cand = self._fresh_mutant(cell.elite, task)
            if cand is not None:
                return Action(kind="exploit_within", task=task, genotype=cand,
                              descriptor=self.bin_rule(cand), seed=self._seed(task, cand),
                              reason="uniform-elite within deepen")
        return None                                    # 모든 채운 셀 포화(상한/중복)

    def _fresh_mutant(self, elite: Genotype, task: str) -> Optional[Genotype]:
        """capacity를 키워 미tried genotype을 만든다. bin이 안 오르거나(상한) 계속 중복이면 None."""
        cand = self.mutate_fn(elite)
        for _ in range(MAX_DEEPEN_GUARD):
            if self.bin_rule(cand) == self.bin_rule(elite):   # bin 안 오름(상한) → 무의미 심화
                return None
            if (task, cand) not in self.tried:
                return cand
            cand = self.mutate_fn(cand)
        return None

    def _cold_start(self) -> Action:
        task = self.tasks[0]
        pick = self.pool[task][0]
        return Action(kind="explore_tier1", task=task, genotype=pick,
                      descriptor=self.bin_rule(pick), seed=self._seed(task, pick),
                      reason="cold start")

    def _best_elite(self) -> Optional[tuple[str, Genotype, tuple[int, int]]]:
        """archive에서 최고 fitness elite (task, genotype, descriptor)를 찾는다.

        Tier2 위임의 출발점 — 에이전트가 이 elite를 보고 더 나은 새 recipe를 저술한다.
        elite 없으면(cold archive) None.
        """
        best: Optional[tuple[str, Genotype, tuple[int, int]]] = None
        best_m = float("-inf")
        for key, cell in self.archive.items():
            if cell.elite is not None and cell.elite_mean() > best_m:
                best_m = cell.elite_mean()
                best = (key[0], cell.elite, cell.descriptor)
        return best

    def _tier2(self) -> Optional[Action]:
        """기존 recipe 격자 소진 → 에이전트에게 새 recipe 저술 위임(SKILL §2c).

        컨트롤러는 새 코드를 못 짜므로(결정론), best elite를 출발점으로 주고 호출자(LLM)가
        새 패러다임을 저술한다. 호출자는 report 시 action.genotype·descriptor를 새 recipe의
        것으로 교체해 보낸다 → placement는 정상. max_tier2 도달 시 None(→ stop).
        """
        if self.tier2_count >= self.cfg.max_tier2:
            return None
        best = self._best_elite()
        if best is None:                            # cold archive — 위임할 출발점 없음
            return None
        self.tier2_count += 1
        task, geno, desc = best
        return Action(kind="explore_tier2", task=task, genotype=geno, descriptor=desc,
                      seed=self._seed(task, geno),
                      reason="coverage exhausted → author new recipe paradigm from best elite")

    # -- placement (RE7) + adaptive sampling (RE6) -------------------------

    def _place(self, cell: Cell, action: Action, fitness: float) -> None:
        """분산인지 elite 교체. 효과크기 미달이면 재평가 escalate."""
        if action.kind == "reeval":
            self._record_reeval(cell, action, fitness)
            return
        cell.evals += 1
        if cell.elite is None:                      # 빈 셀 → 첫 elite
            cell.elite, cell.samples = action.genotype, [fitness]
            return
        if action.genotype == cell.elite:           # 같은 genotype 재측정
            cell.samples = self._capped(cell.samples + [fitness])
            return
        # 다른 genotype 도전 → 도전자로 등록하고 재평가 트리거
        cell.challenger, cell.challenger_samples = action.genotype, [fitness]
        self._maybe_resolve(cell, action.task)

    def _record_reeval(self, cell: Cell, action: Action, fitness: float) -> None:
        cell.evals += 1
        if action.target == "elite":
            cell.samples = self._capped(cell.samples + [fitness])
        else:
            cell.challenger_samples = self._capped(cell.challenger_samples + [fitness])
        self._maybe_resolve(cell, action.task)

    def _maybe_resolve(self, cell: Cell, task: str) -> None:
        """elite vs challenger 효과크기로 교체/유지 판정. 경계면 재평가 큐잉(상한 REEVAL_CAP)."""
        if cell.challenger is None:
            return
        a, b = cell.samples, cell.challenger_samples
        if len(a) < MIN_SAMPLES_FOR_TEST or len(b) < MIN_SAMPLES_FOR_TEST:
            self._enqueue_reeval(cell, task)        # 분산 추정 불가 → 더 모음
            return
        d = cohen_d(a, b)
        if d >= EFFECT_REPLACE:                     # 도전자 유의 우월 → 교체
            cell.elite, cell.samples = cell.challenger, cell.challenger_samples
            cell.challenger, cell.challenger_samples = None, []
        elif abs(d) < EFFECT_BOUNDARY and max(len(a), len(b)) < REEVAL_CAP:
            self._enqueue_reeval(cell, task)        # 경계(의심) → 재평가 escalate(상한 내)
        else:                                       # 도전자 열세 OR 경계인데 충분히 봄 → 기각
            cell.challenger, cell.challenger_samples = None, []

    def _enqueue_reeval(self, cell: Cell, task: str) -> None:
        """표본 적은 쪽 1개만 큐잉. seed는 cell.evals 기반 — 매 재평가 유니크(분산 확보)."""
        if len(cell.samples) <= len(cell.challenger_samples):
            target, n, geno = "elite", len(cell.samples), cell.elite
        else:
            target, n, geno = "challenger", len(cell.challenger_samples), cell.challenger
        if geno is not None and n < REEVAL_CAP:
            self.reeval_queue.append(Action(
                kind="reeval", task=task, genotype=geno, descriptor=cell.descriptor,
                seed=self._seed(task, geno, cell.evals + 1), target=target,
                reason="adaptive sampling: boundary cell"))

    # -- universal 가설검정 (RE8) ------------------------------------------

    def _detect_universals(self) -> None:
        """추상 cap축을 따라 ≥2 recipe가 같은 방향∧효과크기>noise면 보편 가설 기록."""
        directions: dict[str, str] = {}
        for recipe in self._recipes_in_archive():
            d = self._axis_direction(recipe, axis_index=0)   # 0 = cap_bin
            if d:
                directions[recipe] = d
        for direction in ("increasing", "decreasing"):
            members = [r for r, dd in directions.items() if dd == direction]
            if len(members) >= 2 and not self._already_recorded("capacity", direction):
                self.universals.append({"abstract_axis": "capacity", "direction": direction,
                                        "recipes": sorted(members), "found_round": self.round})

    def _axis_direction(self, recipe: str, axis_index: int) -> Optional[str]:
        """한 recipe의 축 추세 방향. **task와 다른 BD축을 둘 다 고정한 슬라이스**에서
        인접 bin 단조성을 보고, 비-flat 슬라이스가 모두 같은 방향일 때만 그 방향을 반환한다.
        task를 통제하지 않으면 task별 절대값 차이(예: patchcore screw 0.5 vs cable 0.9)가
        같은 슬라이스에 섞여 단조성이 깨진다 — illumination marginal은 task·다른축 통제 필수."""
        other = 1 - axis_index
        slices: dict[tuple, list[Cell]] = {}
        for (task, c0, c1), cell in self.archive.items():
            if cell.elite is not None and cell.elite.recipe == recipe:
                slices.setdefault((task, cell.descriptor[other]), []).append(cell)
        dirs = [self._slice_direction(g, axis_index) for g in slices.values()]
        dirs = [d for d in dirs if d in ("increasing", "decreasing")]
        if dirs and all(d == dirs[0] for d in dirs):    # 비-flat 슬라이스 만장일치
            return dirs[0]
        return None

    def _slice_direction(self, group: list[Cell], axis_index: int) -> Optional[str]:
        """한 슬라이스(다른 축 고정)에서 **인접 bin 쌍의 단조성**으로 방향 판정.
        양끝만 보면 비단조 축(증가 후 감소)을 단조로 오판하므로, 인접 쌍 효과크기
        부호가 모두 같을 때만 그 방향을 반환한다(혼재·flat-only면 None)."""
        by_bin = {c.descriptor[axis_index]: c for c in group}
        bins = sorted(by_bin)
        if len(bins) < 2:
            return None
        pair_dirs: list[str] = []
        for lo, hi in zip(bins, bins[1:]):
            d = cohen_d(by_bin[lo].samples, by_bin[hi].samples)
            if d >= EFFECT_UNIVERSAL:
                pair_dirs.append("increasing")
            elif d <= -EFFECT_UNIVERSAL:
                pair_dirs.append("decreasing")
        if pair_dirs and all(p == pair_dirs[0] for p in pair_dirs):
            return pair_dirs[0]
        return None

    # -- 결정론 헬퍼 -------------------------------------------------------

    def _default_mutate(self, elite: Genotype) -> Genotype:
        """도메인 무관 기본 섭동: 첫 수치 config 키를 1.5배. profile이 mutate_fn으로 override."""
        cfg = elite.as_dict()
        for k in sorted(cfg):
            cfg[k] = round(cfg[k] * 1.5, 6)
            break
        return Genotype.of(elite.recipe, cfg)

    def _det_choice(self, items: list):
        """seed 고정 uniform 선택(재현 가능)."""
        return items[self.rng.randrange(len(items))]

    def _seed(self, task: str, geno: Genotype, rep: int = 0) -> int:
        return abs(hash((self.cfg.seed_base, task, geno, rep))) % (2 ** 31)

    def _capped(self, samples: list[float]) -> list[float]:
        return samples[:MAX_SAMPLES_PER_CELL]

    def _recipes_in_archive(self) -> set[str]:
        return {c.elite.recipe for c in self.archive.values() if c.elite is not None}

    def _already_recorded(self, axis: str, direction: str) -> bool:
        return any(u["abstract_axis"] == axis and u["direction"] == direction
                   for u in self.universals)

    def _stop_reason(self) -> str:
        return "universal found" if self.universals else "budget exhausted"

    # -- 관측 --------------------------------------------------------------

    def archive_digest(self) -> tuple:
        """재현성 비교용 결정론 요약(셀별 elite recipe + 반올림 mean)."""
        return tuple(sorted(
            (k, c.elite.recipe, round(c.elite_mean(), 4))
            for k, c in self.archive.items() if c.elite is not None))
