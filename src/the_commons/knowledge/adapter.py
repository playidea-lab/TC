"""evidence(dict) → trends.Sample 어댑터.

`trends.summarize_trends`는 형태 무관 순수 함수이고, 이 어댑터만 evidence 구조
(`pcq_record.config = {recipe_id, **hyperparams}`, `pcq_record.metrics`)를 안다.
경계를 한 곳에 가둬 trends의 순수성을 지킨다.
"""

from __future__ import annotations

from typing import Any

from the_commons.knowledge.trends import Sample


def evidence_to_sample(evidence: dict[str, Any]) -> Sample | None:
    """evidence dict → (recipe_id, config(hyperparams만), metrics). recipe_id 없으면 None."""
    pcq = evidence.get("pcq_record") or {}
    config = dict(pcq.get("config") or {})
    recipe_id = config.pop("recipe_id", None)
    if not isinstance(recipe_id, str) or not recipe_id:
        return None
    metrics = dict(pcq.get("metrics") or {})
    return (recipe_id, config, metrics)
