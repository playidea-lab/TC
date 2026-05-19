"""Serializer template version 1.

자연어 description 한 줄에 핵심 정보 (modality, 크기 대역, intent, hardware,
recipe 추정)를 압축. PHI 차단 정합 — 대역만, 정확값 없음.

version 변경 시 기존 evidence re-embed batch job 발동 (re-derivable).
"""

from typing import Any

from the_commons.library.models import Evidence
from the_commons.matchmaker.serializer.types import QueryFeatures

TEMPLATE_VERSION = "v1"


def serialize_query(query: QueryFeatures) -> str:
    """QueryFeatures → 자연어 description (검색용)."""
    modality = query.data_fingerprint.modality
    band = query.data_fingerprint.sample_count_band
    goal_phrase = _goal_phrase(query.intent.goal)
    expected = _expected_phrase(query.intent)
    hw = _hardware_phrase(query.worker_spec)
    stats = _stats_phrase(query.data_fingerprint.statistical_moments)

    parts = [
        f"{modality} dataset: {band} samples{stats}.",
        f"Hardware: {hw}.",
        f"Goal: {goal_phrase}{expected}.",
    ]
    return " ".join(parts)


def serialize_evidence(evidence: Evidence) -> str:
    """Evidence(envelope) → 자연어 description (검색·rerank용)."""
    pcq = evidence.pcq_record
    fp = pcq.data_fingerprint
    modality = fp.modality if fp else "unknown"
    band = fp.sample_count_band if fp else "unknown"
    recipe = _recipe_phrase(pcq.config)
    metric = _metric_phrase(pcq.metrics)
    goal = pcq.intent.goal if pcq.intent else None
    intent_phrase = _goal_phrase(goal) if goal else "no declared goal"
    tier_phrase = "real" if evidence.tier == "real" else "synthetic (LLM-distilled)"

    return (
        f"{recipe} run on {modality} {band} ({intent_phrase}). "
        f"{metric}. Tier: {tier_phrase}."
    )


# ----------------------------------------------------------------------------
# Phrase builders
# ----------------------------------------------------------------------------

_GOAL_PHRASES: dict[str, str] = {
    "baseline_reproduction": "reproduce a known baseline",
    "sota_challenge": "challenge state-of-the-art",
    "ablation": "isolate the effect of one component",
    "hyperparam_sweep": "tune hyperparameters",
    "exploration": "explore what works on this data",
}


def _goal_phrase(goal: str | None) -> str:
    if goal is None:
        return "no declared goal"
    return _GOAL_PHRASES.get(goal, goal)


def _expected_phrase(intent: Any) -> str:
    expected = getattr(intent, "expected_baseline", None)
    if not isinstance(expected, dict):
        return ""
    metric = expected.get("metric")
    value = expected.get("value")
    if not metric or value is None:
        return ""
    return f" (target {metric}={value})"


def _hardware_phrase(spec: Any) -> str:
    gpu = getattr(spec, "gpu_model", None)
    vram = getattr(spec, "vram_gb", None)
    ram = getattr(spec, "ram_gb", 0)
    cpu = getattr(spec, "cpu_cores", 0)
    if gpu:
        vram_part = f", {vram}GB VRAM" if vram else ""
        return f"GPU {gpu}{vram_part}, {ram}GB RAM"
    return f"CPU {cpu} cores, {ram}GB RAM"


def _stats_phrase(moments: dict[str, Any]) -> str:
    if not moments:
        return ""
    class_balance = moments.get("class_balance")
    missing = moments.get("missing_pct")
    parts = []
    if class_balance:
        parts.append(f"class balance {class_balance}")
    if missing:
        parts.append(f"missing {missing}")
    if not parts:
        return ""
    return f", {', '.join(parts)}"


def _recipe_phrase(config: dict[str, Any]) -> str:
    """config dict에서 recipe 추정. v0.1엔 단순 — 'recipe_id' 또는 framework 키."""
    for key in ("recipe_id", "recipe", "model_family", "framework", "model"):
        value = config.get(key)
        if isinstance(value, str) and value:
            return value
    return "experiment"


def _metric_phrase(metrics: dict[str, Any]) -> str:
    """첫 numeric metric을 'NAME=value' 형태로."""
    for name, value in metrics.items():
        if isinstance(value, int | float):
            return f"Observed: {name}={value:.4g}"
    return "No primary metric"
