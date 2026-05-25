"""KR3: config 축별 metric 추세 순수계산.

같은 recipe evidence들에서 numeric config 축의 (값, metric)을 정렬해 단조성을 판정한다.
LLM·DB·부작용 없는 순수 함수 — 그래서 단위 테스트로 정확성을 검증할 수 있다(KR10).
출력은 '사실(추세)'만 담고 처방(next_config)은 담지 않는다(KR6: 판단은 에이전트).
categorical/target 축은 범위 밖(다음 조각).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

# (recipe_id, config, metrics) — Evidence에서 뽑은 가벼운 입력. 순수 함수라 무거운
# 봉투를 받지 않는다(테스트 용이). Evidence→Sample 변환은 호출측 어댑터의 몫.
Sample = tuple[str, dict, dict]

# 추세를 낼 만한 최소 유니크 축값 수 (1개면 비교 불가)
_MIN_UNIQUE_POINTS = 2


@dataclass(frozen=True)
class AxisTrend:
    """한 config 축의 metric 추세 — 사실만(처방 없음)."""

    axis: str
    direction: str  # "increasing" | "decreasing" | "non_monotonic"
    points: tuple[tuple[float, float], ...]  # (config_value, metric), 축값 오름차순


@dataclass(frozen=True)
class RecipeTrend:
    """한 recipe의 축별 추세 묶음."""

    recipe_id: str
    metric: str
    axes: tuple[AxisTrend, ...]


def _is_numeric(value: object) -> bool:
    # bool은 int 서브클래스라 명시적으로 제외 (numeric 축이 아님)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _direction(metrics_in_axis_order: list[float]) -> str:
    """축값 오름차순으로 정렬된 metric 수열의 단조성."""
    diffs = [b - a for a, b in zip(metrics_in_axis_order, metrics_in_axis_order[1:])]
    if all(d >= 0 for d in diffs):
        return "increasing"
    if all(d <= 0 for d in diffs):
        return "decreasing"
    return "non_monotonic"


def summarize_trends(samples: list[Sample], metric: str) -> list[RecipeTrend]:
    """recipe별로 numeric config 축의 metric 추세를 계산한다.

    유니크 축값이 2개 미만인 축(고정값 등)은 추세가 무의미하므로 제외한다.
    """
    by_recipe: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_recipe[sample[0]].append(sample)

    result: list[RecipeTrend] = []
    for recipe_id, group in by_recipe.items():
        axis_keys = {
            key
            for _, config, _ in group
            for key, value in config.items()
            if _is_numeric(value)
        }
        axes: list[AxisTrend] = []
        for axis in sorted(axis_keys):
            points = [
                (float(config[axis]), float(metrics[metric]))
                for _, config, metrics in group
                if axis in config and metric in metrics
            ]
            if len({x for x, _ in points}) < _MIN_UNIQUE_POINTS:
                continue
            points.sort(key=lambda p: p[0])
            axes.append(
                AxisTrend(
                    axis=axis,
                    direction=_direction([y for _, y in points]),
                    points=tuple(points),
                )
            )
        result.append(RecipeTrend(recipe_id=recipe_id, metric=metric, axes=tuple(axes)))
    return result
