"""P0 — 합성 fitness landscape로 MAP-Elites 컨트롤러 단위검증.

실데이터(비싼 ML 학습) 전에 알고리즘 정합을 증명한다. 노이즈를 주입한 알려진 landscape에서
컨트롤러가 (1) cross-recipe binning 정규화 (2) uniform 재현 (3) 분산인지 placement(lucky-swap
차단) (4) adaptive sampling escalate (5) universal 가설검정(정답 gradient 탐지·노이즈축 오탐 없음)
(6) 전체 재현성을 옳게 수행하는지 검증한다.
"""

from __future__ import annotations

import math
import random
import unittest

from the_commons.exploration.map_elites import (
    REEVAL_CAP,
    Action,
    Cell,
    ControllerConfig,
    Genotype,
    MapElitesController,
    cohen_d,
)

# ----------------------------------------------------------------------------
# 합성 landscape — cap축은 증가(보편 정답), loc축은 비단조(보편 아님)
# ----------------------------------------------------------------------------

CAP_GAIN = 0.06          # cap_bin당 fitness 증가 (노이즈보다 크게 → large effect)
SIGMA = 0.01             # 평가 노이즈 표준편차
TASK_BASE = {"screw": 0.70, "pill": 0.72}
RECIPE_BIAS = {"patchcore": 0.02, "padim": 0.00, "ae": -0.01}


def cap_bin_of(recipe: str, cfg: dict[str, float]) -> int:
    """RE2 객관 binning — recipe별 구체 capacity 축을 같은 척도(log10)로 정규화."""
    if recipe == "patchcore":
        raw = cfg["memory"]            # 예: 100~1e6
    elif recipe == "padim":
        raw = cfg["nfeat"] * 100.0     # 스케일 다름 → ×100로 정규화
    else:
        raw = cfg["latent"] * 1000.0   # ae latent → ×1000
    return max(0, min(4, round(math.log10(max(raw, 1.0))) - 2))


def loc_bin_of(cfg: dict[str, float]) -> int:
    return int(max(0, min(4, cfg.get("loc", 0))))


def bin_rule(g: Genotype) -> tuple[int, int]:
    cfg = g.as_dict()
    return cap_bin_of(g.recipe, cfg), loc_bin_of(cfg)


def landscape(action: Action) -> float:
    """알려진 fitness: cap_bin 증가 + loc 비단조 + recipe bias + 결정론 노이즈(seed)."""
    rng = random.Random(action.seed)
    cap_bin, loc_bin = action.descriptor
    base = TASK_BASE[action.task]
    cap_term = CAP_GAIN * cap_bin
    loc_term = -abs(loc_bin - 2) * 0.015           # 2에서 최대 → 비단조
    bias = RECIPE_BIAS[action.genotype.recipe]
    val = base + cap_term + loc_term + bias + rng.gauss(0, SIGMA)
    return max(0.0, min(1.0, val))


CAP_KEY = {"patchcore": "memory", "padim": "nfeat", "ae": "latent"}


def make_pool(tasks: list[str]) -> dict[str, list[Genotype]]:
    """각 recipe × cap_bin × loc_bin 후보(Tier1 미사용 recipe 격자 채움용).
    loc 전 구간(0~4)을 채워야 비단조 축이 archive에 드러난다."""
    raw_by_recipe = {
        "patchcore": ("memory", [100, 1000, 10000, 100000, 1000000]),
        "padim": ("nfeat", [1, 10, 100, 1000, 10000]),
        "ae": ("latent", [0.1, 1, 10, 100, 1000]),
    }
    pool: dict[str, list[Genotype]] = {}
    for task in tasks:
        genos: list[Genotype] = []
        for recipe, (key, raws) in raw_by_recipe.items():
            for raw in raws:
                for loc in (0, 1, 2, 3, 4):
                    genos.append(Genotype.of(recipe, {key: float(raw), "loc": float(loc)}))
        pool[task] = genos
    return pool


def capacity_mutate(g: Genotype) -> Genotype:
    """within-recipe 섭동 — capacity 축만 1.5배(loc 유지). profile mutate_fn 역할(P0)."""
    cfg = g.as_dict()
    key = CAP_KEY[g.recipe]
    cfg[key] = round(cfg[key] * 1.5, 6)
    return Genotype.of(g.recipe, cfg)


def run_to_completion(controller: MapElitesController) -> None:
    guard = 0
    while guard < 5000:
        guard += 1
        action = controller.step()
        if action.kind == "stop":
            return
        controller.report(action, landscape(action))
    raise AssertionError("컨트롤러가 종료하지 않음(무한루프 의심)")


def build(seed: int = 7, epsilon: float = 0.4, budget: int = 120) -> MapElitesController:
    tasks = ["screw", "pill"]
    return MapElitesController(
        ControllerConfig(epsilon=epsilon, budget=budget, seed_base=seed),
        bin_rule, tasks, make_pool(tasks), mutate_fn=capacity_mutate)


# ----------------------------------------------------------------------------
# 테스트
# ----------------------------------------------------------------------------


class Test_binning_NormalizesCrossRecipe(unittest.TestCase):
    def test_different_concrete_axes_map_to_same_cap_bin(self) -> None:
        # patchcore memory=50000, padim nfeat=550, ae latent=55 → 같은 capacity 척도
        a = Genotype.of("patchcore", {"memory": 50000.0, "loc": 0.0})
        b = Genotype.of("padim", {"nfeat": 550.0, "loc": 0.0})
        c = Genotype.of("ae", {"latent": 55.0, "loc": 0.0})
        self.assertEqual(bin_rule(a)[0], bin_rule(b)[0])
        self.assertEqual(bin_rule(b)[0], bin_rule(c)[0])


class Test_select_Reproducible(unittest.TestCase):
    def test_same_seed_yields_identical_action_sequence(self) -> None:
        seqs = []
        for _ in range(2):
            ctrl = build(seed=11, budget=30)
            actions = []
            guard = 0
            while guard < 200:
                guard += 1
                a = ctrl.step()
                if a.kind == "stop":
                    break
                actions.append((a.kind, a.task, a.genotype.recipe, a.descriptor))
                ctrl.report(a, landscape(a))
            seqs.append(actions)
        self.assertEqual(seqs[0], seqs[1])


class Test_placement_VarianceAware(unittest.TestCase):
    def _resolved_cell(self, elite_vals, chal_vals) -> Cell:
        """elite·challenger 표본을 강제 주입하고 _maybe_resolve를 끝까지 돌린 셀 반환."""
        ctrl = build()
        cell = Cell(descriptor=(2, 0))
        elite = Genotype.of("patchcore", {"memory": 1e4, "loc": 0.0})
        chal = Genotype.of("padim", {"nfeat": 1e2, "loc": 0.0})
        cell.elite, cell.samples = elite, list(elite_vals[:1])
        ctrl.archive[("screw", 2, 0)] = cell
        # 첫 도전(challenger 1표본)
        ctrl.report(Action(kind="explore_tier1", task="screw", genotype=chal,
                           descriptor=(2, 0)), chal_vals[0])
        # adaptive sampling 큐를 제어된 값으로 소진
        ei, ci = 1, 1
        guard = 0
        while ctrl.reeval_queue and guard < 50:
            guard += 1
            act = ctrl.reeval_queue.pop(0)
            if act.target == "elite":
                v = elite_vals[min(ei, len(elite_vals) - 1)]; ei += 1
            else:
                v = chal_vals[min(ci, len(chal_vals) - 1)]; ci += 1
            ctrl.report(act, v)
        return ctrl.archive[("screw", 2, 0)]

    def test_lucky_high_noise_does_not_replace_true_elite(self) -> None:
        # elite 진짜 우월(0.90±), challenger 첫값만 운좋게 0.93, 실제는 0.70±
        cell = self._resolved_cell(
            elite_vals=[0.90, 0.91, 0.89, 0.90, 0.905],
            chal_vals=[0.93, 0.70, 0.71, 0.69, 0.70])
        self.assertEqual(cell.elite.recipe, "patchcore")

    def test_true_winner_replaces_elite(self) -> None:
        # challenger 일관되게 우월(0.95±) → 교체
        cell = self._resolved_cell(
            elite_vals=[0.80, 0.81, 0.79, 0.80, 0.805],
            chal_vals=[0.95, 0.96, 0.94, 0.95, 0.955])
        self.assertEqual(cell.elite.recipe, "padim")


class Test_adaptiveSampling_Escalates(unittest.TestCase):
    def test_boundary_cell_enqueues_reeval_and_grows_samples(self) -> None:
        ctrl = build()
        cell = Cell(descriptor=(2, 0))
        elite = Genotype.of("patchcore", {"memory": 1e4, "loc": 0.0})
        chal = Genotype.of("padim", {"nfeat": 1e2, "loc": 0.0})
        cell.elite, cell.samples = elite, [0.80]
        ctrl.archive[("screw", 2, 0)] = cell
        # 근소차 도전자 → 경계 → 재평가 escalate
        ctrl.report(Action(kind="explore_tier1", task="screw", genotype=chal,
                           descriptor=(2, 0)), 0.805)
        self.assertTrue(len(ctrl.reeval_queue) >= 1)
        self.assertTrue(all(a.kind == "reeval" for a in ctrl.reeval_queue))


class Test_universal_HypothesisTest(unittest.TestCase):
    def test_true_capacity_gradient_detected_across_recipes(self) -> None:
        ctrl = build(seed=7, epsilon=0.5, budget=200)
        run_to_completion(ctrl)
        caps = [u for u in ctrl.universals
                if u["abstract_axis"] == "capacity" and u["direction"] == "increasing"]
        self.assertTrue(caps, "정답 cap↑ gradient를 보편 가설로 탐지해야 함")
        self.assertGreaterEqual(len(caps[0]["recipes"]), 2, "≥2 recipe 횡단이어야 함")

    def _seed_axis(self, ctrl: MapElitesController, axis_index: int,
                   means: dict[int, float]) -> None:
        """한 축을 따라 명시적 mean을 가진 patchcore 셀을 archive에 직접 주입(다른 축 고정=2)."""
        for idx, m in means.items():
            desc = (idx, 2) if axis_index == 0 else (2, idx)
            cell = Cell(descriptor=desc)
            cell.elite = Genotype.of("patchcore", {"memory": 1e4, "loc": float(desc[1])})
            cell.samples = [m - 0.002, m, m + 0.002]      # 작은 분산
            ctrl.archive[("screw", *desc)] = cell

    def test_nonmonotone_axis_not_flagged(self) -> None:
        # 비단조(2에서 최대)는 인접쌍 부호 혼재 → None (universal 가설 아님)
        ctrl = build()
        self._seed_axis(ctrl, axis_index=1,
                        means={0: 0.70, 1: 0.74, 2: 0.78, 3: 0.74, 4: 0.70})
        self.assertIsNone(ctrl._axis_direction("patchcore", axis_index=1))

    def test_monotone_axis_flagged_increasing(self) -> None:
        # 대조군: 단조 증가는 increasing으로 판정
        ctrl = build()
        self._seed_axis(ctrl, axis_index=0,
                        means={0: 0.70, 1: 0.76, 2: 0.82, 3: 0.88, 4: 0.94})
        self.assertEqual(ctrl._axis_direction("patchcore", axis_index=0), "increasing")

    def test_capacity_gradient_detected_despite_task_offset(self) -> None:
        # 결함6(실주행): task별 절대값이 크게 달라도(screw 0.5대, pill 0.9대) 각 task에서
        # cap↑이면 increasing. task를 통제하지 않으면 섞여서 단조성이 깨진다.
        ctrl = build()
        for task, base in [("screw", 0.50), ("pill", 0.90)]:
            for cap, inc in [(1, 0.0), (2, 0.04), (3, 0.08)]:
                cell = Cell(descriptor=(cap, 2))
                cell.elite = Genotype.of("patchcore", {"memory": 10.0 ** (cap + 2), "loc": 2.0})
                m = base + inc
                cell.samples = [m - 0.002, m, m + 0.002]
                ctrl.archive[(task, cap, 2)] = cell
        self.assertEqual(ctrl._axis_direction("patchcore", axis_index=0), "increasing")


class Test_fullRun_Reproducible(unittest.TestCase):
    def test_same_seed_identical_archive_digest(self) -> None:
        digests = []
        for _ in range(2):
            ctrl = build(seed=23, epsilon=0.4, budget=150)
            run_to_completion(ctrl)
            digests.append(ctrl.archive_digest())
        self.assertEqual(digests[0], digests[1])


class Test_operationalDefects(unittest.TestCase):
    """실주행(P4)이 잡은 결함들의 회귀 — P0 합성이 못 본 운영 시나리오."""

    def test_reeval_seeds_are_unique(self) -> None:
        # 결함1: 경계 셀 재평가 seed가 매번 달라야(시드별 독립 run → 분산 확보)
        ctrl = build()
        cell = Cell(descriptor=(2, 0), evals=1)
        cell.elite = Genotype.of("patchcore", {"memory": 1e4, "loc": 0.0})
        cell.samples = [0.80]
        ctrl.archive[("screw", 2, 0)] = cell
        chal = Genotype.of("padim", {"nfeat": 1e2, "loc": 0.0})
        ctrl.report(Action(kind="explore_tier1", task="screw", genotype=chal,
                           descriptor=(2, 0)), 0.805)          # 근소차 → 경계
        seeds, guard = [], 0
        while ctrl.reeval_queue and guard < 30:
            guard += 1
            act = ctrl.reeval_queue.pop(0)
            seeds.append(act.seed)
            ctrl.report(act, 0.80 if act.target == "elite" else 0.805)
        self.assertEqual(len(seeds), len(set(seeds)), "reeval seed 중복(결함1 회귀)")
        self.assertLessEqual(len(seeds), 2 * REEVAL_CAP, "reeval 폭주(결함2 회귀)")

    def test_zero_variance_challenger_rejected_and_bounded(self) -> None:
        # 결함3: 0분산 동일값 challenger → 유한 횟수 후 기각(무한루프 없음)
        ctrl = build()
        cell = Cell(descriptor=(3, 2), evals=1)
        cell.elite = Genotype.of("padim", {"nfeat": 500.0, "loc": 2.0})
        cell.samples = [0.8012]
        ctrl.archive[("cable", 3, 2)] = cell
        chal = Genotype.of("padim", {"nfeat": 600.0, "loc": 2.0})   # 다른 genotype, 같은 값
        ctrl.report(Action(kind="explore_tier1", task="cable", genotype=chal,
                           descriptor=(3, 2)), 0.8012)
        guard = 0
        while ctrl.reeval_queue and guard < 50:
            guard += 1
            ctrl.report(ctrl.reeval_queue.pop(0), 0.8012)        # 항상 동일값
        self.assertLess(guard, 50, "0분산 무한 reeval(결함3 회귀)")
        self.assertIsNone(ctrl.archive[("cable", 3, 2)].challenger, "동일값 challenger 미기각")

    def test_exploit_emits_no_duplicate_genotype(self) -> None:
        # 결함4: exploit_within이 같은 (task, genotype)을 반복하지 않음
        ctrl = build(seed=5, epsilon=0.0, budget=25)             # 항상 exploit 우선
        seen: set = set()
        guard = 0
        while guard < 60:
            guard += 1
            a = ctrl.step()
            if a.kind == "stop":
                break
            if a.kind == "exploit_within":
                key = (a.task, a.genotype)
                self.assertNotIn(key, seen, f"exploit 중복 genotype(결함4): {a.genotype.recipe}")
                seen.add(key)
            ctrl.report(a, landscape(a))


class Test_cohenD(unittest.TestCase):
    def test_returns_zero_when_insufficient_samples(self) -> None:
        self.assertEqual(cohen_d([0.9], [0.8]), 0.0)

    def test_positive_when_b_greater(self) -> None:
        d = cohen_d([0.10, 0.11, 0.09], [0.50, 0.51, 0.49])
        self.assertGreater(d, 0.8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
