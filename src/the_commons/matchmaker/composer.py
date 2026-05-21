"""Response composer — rerank 결과 + corpus context를 API 응답 형태로."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from the_commons.library.models import Evidence
from the_commons.llm.protocol import RankedCandidate
from the_commons.matchmaker.retriever import RetrievedHit

ConfidenceLabel = Literal["strong", "medium", "weak_heuristic", "synthetic_dominant"]


@dataclass(frozen=True)
class CorpusContext:
    """추천 응답 상단에 항상 표시되는 라벨 — README "Always labeled" 약속."""

    real_count: int
    synthetic_count: int

    @property
    def total(self) -> int:
        return self.real_count + self.synthetic_count

    @property
    def is_synthetic_dominant(self) -> bool:
        if self.total == 0:
            return False
        return self.synthetic_count > self.real_count


@dataclass(frozen=True)
class ComposedCandidate:
    """최종 응답 한 항목.

    v1 (cq-tc-autonomous-experiment-loop)에서 추가:
    - next_config: ε-novelty mix 정책이 합성한 다음 시도 hyperparam dict.
      cq가 그대로 받아 학습 실행. cold-start나 기존 호환 클라이언트 위해 optional.
    - policy: {branch, epsilon, version, wild_card_fired} 메타데이터.
      envelope.attribution.policy로 박혀 사후 v1→v2 정책 비교의 기준.
    """

    recipe_id: str
    expected_metric: dict[str, float] | None
    evidence_ids: list[str]
    confidence: ConfidenceLabel
    reasoning: str
    next_config: dict[str, Any] | None = None
    policy: dict[str, Any] | None = field(default=None)


def summarize_corpus(hits: list[RetrievedHit]) -> CorpusContext:
    """retrieve hits로부터 real/synthetic 비율 계산."""
    tier_counts = Counter(h.tier for h in hits)
    return CorpusContext(
        real_count=tier_counts.get("real", 0),
        synthetic_count=tier_counts.get("synthetic", 0),
    )


def classify_confidence(
    context: CorpusContext,
    *,
    is_heuristic_fallback: bool,
) -> ConfidenceLabel:
    """corpus 상태로부터 신뢰도 라벨 결정."""
    if is_heuristic_fallback:
        return "weak_heuristic"
    if context.is_synthetic_dominant:
        return "synthetic_dominant"
    if context.real_count >= 3:
        return "strong"
    return "medium"


def compose_candidates(
    ranked: list[RankedCandidate],
    *,
    fetched_evidence: list[Evidence],
    confidence: ConfidenceLabel,
) -> list[ComposedCandidate]:
    """RankedCandidate list를 API 응답 형식으로 변환.

    각 ranked 항목의 index가 fetched_evidence list의 위치를 가리킨다.
    """
    composed: list[ComposedCandidate] = []
    for r in ranked:
        if not 0 <= r.index < len(fetched_evidence):
            continue
        ev = fetched_evidence[r.index]
        composed.append(
            ComposedCandidate(
                recipe_id=_extract_recipe_id(ev),
                expected_metric=_extract_primary_metric(ev),
                evidence_ids=[ev.evidence_id],
                confidence=confidence,
                reasoning=r.reasoning,
            )
        )
    return composed


def _extract_recipe_id(evidence: Evidence) -> str:
    """pcq_record.config에서 recipe identifier 추출 (serializer와 같은 규칙)."""
    for key in ("recipe_id", "recipe", "model_family", "framework", "model"):
        value = evidence.pcq_record.config.get(key)
        if isinstance(value, str) and value:
            return value
    return "experiment"


def _extract_primary_metric(evidence: Evidence) -> dict[str, float] | None:
    """첫 numeric metric을 {"name": ..., "value": ...}로."""
    for name, value in evidence.pcq_record.metrics.items():
        if isinstance(value, int | float):
            return {"name": name, "value": float(value)}
    return None
