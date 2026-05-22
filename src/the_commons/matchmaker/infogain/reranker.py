"""InfoGainReranker — 정보이득 하이브리드 reranker 결선 (ID1~ID4).

retrieved 이웃을 recipe별로 묶고, 각 recipe의 Beta 사후를
  prior(저데이터면 LLM informed, 아니면 weak uniform) → 정규화 관측 update
로 요청 시점에 fit한 뒤, 후보를 그 recipe의 *기대 엔트로피 감소*
(expected_info_gain) 내림차순으로 랭킹한다.

평평한(덜 탐사된) recipe일수록 정보이득이 커서 상위에 온다 — "불확실한
것을 먼저 탐사하라"는 active-learning 신호 (ID2). 음성·실패가 많이 쌓여
뾰족해진 recipe는 정보이득이 작아 자연히 하위로 내려간다.

v0.1 텍스트 전용 listwise rerank를 대체한다. 텍스트가 아니라 구조적
Evidence(metric·intent·tier)가 필요하므로 LLMReranker Protocol이 아닌
독자 인터페이스를 쓴다 (service.py가 step5 fetched records를 전달).
"""

from __future__ import annotations

from the_commons.library.models import Evidence
from the_commons.llm.protocol import RankedCandidate
from the_commons.matchmaker.composer import _extract_recipe_id
from the_commons.matchmaker.infogain.llm_prior import (
    WEAK_DEFAULT_PRIOR,
    PriorLLM,
    llm_beta_priors_batch,
)
from the_commons.matchmaker.infogain.normalize import normalize_neighborhood
from the_commons.matchmaker.infogain.posterior import BetaPosterior
from the_commons.matchmaker.retriever import RetrievedHit
from the_commons.settings import settings


class InfoGainReranker:
    """정보이득 기준 reranker. llm은 저데이터 regime prior 공급용."""

    def __init__(self, *, llm: PriorLLM) -> None:
        self._llm = llm

    async def rerank(
        self,
        query: str,
        hits: list[RetrievedHit],
        records: list[Evidence],
        top_n: int = 5,
    ) -> list[RankedCandidate]:
        if not records:
            return []

        scores = normalize_neighborhood(records)

        # recipe별 멤버 (records 내 위치 보존 — RankedCandidate.index)
        groups: dict[str, list[int]] = {}
        for idx, ev in enumerate(records):
            groups.setdefault(_extract_recipe_id(ev), []).append(idx)

        # 저데이터 recipe(real < threshold)만 LLM prior가 필요 → 1회 배치 호출로
        # 직렬 N회를 회피한다. 고데이터 recipe는 likelihood 우세라 weak default.
        low_data = [
            recipe_id
            for recipe_id, idxs in groups.items()
            if sum(1 for i in idxs if records[i].tier == "real")
            < settings.retirement_real_threshold
        ]
        priors = await llm_beta_priors_batch(low_data, query, llm=self._llm)

        # recipe별 사후 fit — 배치 결과에 없거나 고데이터면 weak default
        recipe_post: dict[str, BetaPosterior] = {}
        recipe_gain: dict[str, float] = {}
        for recipe_id, idxs in groups.items():
            members = [records[i] for i in idxs]
            obs = [
                scores[ev.evidence_id]
                for ev in members
                if ev.evidence_id in scores
            ]
            a0, b0 = priors.get(recipe_id, WEAK_DEFAULT_PRIOR)
            post = BetaPosterior(a0, b0).update(obs)
            recipe_post[recipe_id] = post
            recipe_gain[recipe_id] = post.expected_info_gain()

        # 후보를 recipe 정보이득 내림차순 (동률은 similarity로 결정적 정렬)
        sim_by_id = {h.evidence_id: h.similarity for h in hits}

        def _sort_key(idx: int) -> tuple[float, float]:
            ev = records[idx]
            recipe_id = _extract_recipe_id(ev)
            return (
                recipe_gain[recipe_id],
                sim_by_id.get(ev.evidence_id, 0.0),
            )

        ordered = sorted(range(len(records)), key=_sort_key, reverse=True)

        ranked: list[RankedCandidate] = []
        for idx in ordered[:top_n]:
            ev = records[idx]
            recipe_id = _extract_recipe_id(ev)
            post = recipe_post[recipe_id]
            gain = recipe_gain[recipe_id]
            ranked.append(
                RankedCandidate(
                    index=idx,
                    score=gain,
                    reasoning=(
                        f"recipe={recipe_id} posterior mean={post.mean():.3f} "
                        f"uncertainty(entropy)={post.entropy():.3f} "
                        f"expected info gain={gain:.4f}"
                    ),
                )
            )
        return ranked
