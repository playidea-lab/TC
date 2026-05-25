"""Synthesizer 단위 테스트 — LLM이 next_config를 합성하는 v1의 핵심 모듈.

WithinRecipeSynthesizer: 한 recipe 안에서 evidence history + intent → 다음 config.
NoveltyRecipeSynthesizer: corpus 분포 + intent → corpus 밖 새 recipe + config.

RR6 정합: LLM 예외/스키마 위반은 추천 중단 금지 → fallback proposal 반환.
"""

from __future__ import annotations

from typing import Any

import pytest

from the_commons.matchmaker.synthesizer import (
    EvidenceSummary,
    NextConfigProposal,
    NoveltyRecipeSynthesizer,
    RecipeStats,
    WithinRecipeSynthesizer,
)


class _MockLLM:
    """SynthesisLLM Protocol을 만족하는 결정적 mock."""

    def __init__(self, response: str | Exception):
        self._response = response
        self.last_prompt: str | None = None

    async def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


# ---------- WithinRecipeSynthesizer ----------


@pytest.mark.asyncio
async def test_within_recipe_returns_proposal_from_valid_json() -> None:
    """LLM이 JSON으로 next_config를 반환하면 NextConfigProposal에 박혀야 한다."""
    llm = _MockLLM(
        '{"recipe_id": "mnist-tinymlp", '
        '"next_config": {"lr": 0.03, "batch_size": 256, "epochs": 1}, '
        '"reasoning": "lr=0.01에서 best, 살짝 키워봄"}'
    )
    synth = WithinRecipeSynthesizer(llm=llm)
    evidences = [
        EvidenceSummary(
            evidence_id="ev-1",
            config={"lr": 0.001, "batch_size": 128},
            metrics={"test_acc": 0.88},
        ),
        EvidenceSummary(
            evidence_id="ev-2",
            config={"lr": 0.01, "batch_size": 128},
            metrics={"test_acc": 0.97},
        ),
    ]

    proposal = await synth.propose(
        recipe_id="mnist-tinymlp", evidences=evidences, intent="acc 더 올리기"
    )

    assert isinstance(proposal, NextConfigProposal)
    assert proposal.recipe_id == "mnist-tinymlp"
    assert proposal.next_config["lr"] == 0.03
    assert proposal.next_config["batch_size"] == 256
    assert "ev-1" in proposal.evidence_ids and "ev-2" in proposal.evidence_ids
    assert llm.last_prompt is not None
    # prompt 안에 evidence config/metric 흔적이 있어야 — LLM이 history를 봐야 함
    assert "0.97" in llm.last_prompt or "0.01" in llm.last_prompt


@pytest.mark.asyncio
async def test_within_recipe_falls_back_on_llm_exception() -> None:
    """LLM이 예외를 던지면 fallback proposal 반환 (추천 중단 금지)."""
    llm = _MockLLM(RuntimeError("LLM down"))
    synth = WithinRecipeSynthesizer(llm=llm)
    evidences = [
        EvidenceSummary(
            evidence_id="ev-1", config={"lr": 0.01}, metrics={"test_acc": 0.9}
        )
    ]

    proposal = await synth.propose(
        recipe_id="mnist-tinymlp", evidences=evidences, intent="x"
    )

    assert proposal.recipe_id == "mnist-tinymlp"  # 같은 recipe 유지
    assert isinstance(proposal.next_config, dict)
    assert proposal.next_config  # 비어있지 않음 — fallback config 채워짐
    assert "fallback" in proposal.reasoning.lower()


@pytest.mark.asyncio
async def test_within_recipe_falls_back_on_schema_violation() -> None:
    """LLM이 JSON 아닌 텍스트나 필드 누락 시 fallback."""
    llm = _MockLLM("이건 JSON이 아닙니다 죄송")
    synth = WithinRecipeSynthesizer(llm=llm)
    evidences = [
        EvidenceSummary(evidence_id="ev-1", config={"lr": 0.01}, metrics={})
    ]

    proposal = await synth.propose(
        recipe_id="mnist-tinymlp", evidences=evidences, intent="x"
    )

    assert proposal.recipe_id == "mnist-tinymlp"
    assert "fallback" in proposal.reasoning.lower()


@pytest.mark.asyncio
async def test_within_recipe_falls_back_on_wrong_field_types() -> None:
    """next_config가 dict가 아니면 fallback."""
    llm = _MockLLM(
        '{"recipe_id": "mnist-tinymlp", "next_config": "lr=0.01", "reasoning": "x"}'
    )
    synth = WithinRecipeSynthesizer(llm=llm)
    evidences = [
        EvidenceSummary(evidence_id="ev-1", config={"lr": 0.01}, metrics={})
    ]

    proposal = await synth.propose(
        recipe_id="mnist-tinymlp", evidences=evidences, intent="x"
    )

    assert isinstance(proposal.next_config, dict)
    assert "fallback" in proposal.reasoning.lower()


# ---------- WithinRecipe: 이미 시도한 config 제외 (정체 방지) ----------


@pytest.mark.asyncio
async def test_within_prompt_lists_tried_configs() -> None:
    """프롬프트에 이미 시도한 distinct config가 '제외 대상'으로 명시돼야 한다."""
    llm = _MockLLM('{"recipe_id":"r","next_config":{"lr":0.05},"reasoning":"x"}')
    synth = WithinRecipeSynthesizer(llm=llm)
    evs = [
        EvidenceSummary(evidence_id="e1", config={"lr": 0.0005}, metrics={"test_acc": 0.96}),
        EvidenceSummary(evidence_id="e2", config={"lr": 0.0005}, metrics={"test_acc": 0.96}),
    ]
    await synth.propose(recipe_id="r", evidences=evs, intent="acc")
    assert llm.last_prompt is not None
    # tried config(0.0005)가 명시 + "다른 값" 지시
    assert "0.0005" in llm.last_prompt
    assert "시도" in llm.last_prompt  # "이미 시도한" 류 문구


@pytest.mark.asyncio
async def test_within_guard_perturbs_when_llm_repeats_tried_config() -> None:
    """LLM이 이미 시도한 config를 그대로 반환하면 가드가 lr을 바꿔 탐색 강제."""
    # evidences에 lr=0.0005만 있고, LLM도 0.0005를 반복 제안
    llm = _MockLLM('{"recipe_id":"r","next_config":{"lr":0.0005},"reasoning":"또 0.0005"}')
    synth = WithinRecipeSynthesizer(llm=llm)
    evs = [
        EvidenceSummary(evidence_id="e1", config={"lr": 0.0005}, metrics={"test_acc": 0.96}),
    ]
    p = await synth.propose(recipe_id="r", evidences=evs, intent="acc")
    # 가드가 작동해 lr이 0.0005가 아니어야 (탐색 강제)
    assert p.next_config["lr"] != 0.0005
    assert "perturb" in p.reasoning.lower() or "탐색" in p.reasoning


@pytest.mark.asyncio
async def test_within_guard_handles_learning_rate_key_and_recipe_id() -> None:
    """저장 config엔 recipe_id 포함 + learning_rate 키. 정규화 후 중복 판정·perturbation."""
    # 저장된 evidence config: recipe_id 합쳐짐 + learning_rate 키 (cifar 계열 모사)
    stored = {"recipe_id": "cifar10-resnet18", "model": "ResNet18", "learning_rate": 0.0005}
    # LLM이 recipe_id 없이 같은 config 반복
    llm = _MockLLM(
        '{"recipe_id":"cifar10-resnet18","next_config":{"model":"ResNet18","learning_rate":0.0005},"reasoning":"또"}'
    )
    synth = WithinRecipeSynthesizer(llm=llm)
    evs = [EvidenceSummary(evidence_id="e1", config=stored, metrics={"test_acc": 0.96})]
    p = await synth.propose(recipe_id="cifar10-resnet18", evidences=evs, intent="acc")
    # learning_rate가 0.0005에서 밀려야
    assert p.next_config["learning_rate"] != 0.0005


@pytest.mark.asyncio
async def test_within_no_perturb_when_llm_proposes_new_config() -> None:
    """LLM이 미탐색 config를 제안하면 그대로 통과 (가드 미발동)."""
    llm = _MockLLM('{"recipe_id":"r","next_config":{"lr":0.05},"reasoning":"새 값"}')
    synth = WithinRecipeSynthesizer(llm=llm)
    evs = [
        EvidenceSummary(evidence_id="e1", config={"lr": 0.0005}, metrics={"test_acc": 0.96}),
    ]
    p = await synth.propose(recipe_id="r", evidences=evs, intent="acc")
    assert p.next_config["lr"] == 0.05  # 그대로


# ---------- NoveltyRecipeSynthesizer ----------


@pytest.mark.asyncio
async def test_novelty_recipe_returns_new_recipe_from_llm() -> None:
    """LLM이 corpus 밖 새 recipe를 제안하면 proposal에 박혀야 한다."""
    llm = _MockLLM(
        '{"recipe_id": "mnist-resnet18", '
        '"next_config": {"lr": 0.001, "batch_size": 128, "model": "resnet18"}, '
        '"reasoning": "지금까지 tinyMLP만 시도했음. 더 큰 모델 한 번."}'
    )
    synth = NoveltyRecipeSynthesizer(llm=llm)
    corpus = [
        RecipeStats(recipe_id="mnist-tinymlp", tries=8, best_metric=0.97, metric_name="test_acc"),
        RecipeStats(recipe_id="mnist-tinymlp-deep", tries=2, best_metric=0.94, metric_name="test_acc"),
    ]

    proposal = await synth.propose(corpus_recipes=corpus, intent="더 큰 모델 시도")

    assert proposal.recipe_id == "mnist-resnet18"
    assert "model" in proposal.next_config
    assert proposal.evidence_ids == []  # novelty라 backing evidence 없음
    assert llm.last_prompt is not None
    # prompt 안에 기존 recipe 분포가 보여야 — LLM이 corpus를 봐야 함
    assert "mnist-tinymlp" in llm.last_prompt


@pytest.mark.asyncio
async def test_novelty_recipe_falls_back_on_llm_exception() -> None:
    """LLM 예외 시 fallback proposal 반환."""
    llm = _MockLLM(TimeoutError("timeout"))
    synth = NoveltyRecipeSynthesizer(llm=llm)
    corpus = [
        RecipeStats(
            recipe_id="mnist-tinymlp", tries=3, best_metric=0.9, metric_name="test_acc"
        )
    ]

    proposal = await synth.propose(corpus_recipes=corpus, intent="x")

    assert isinstance(proposal, NextConfigProposal)
    assert proposal.recipe_id  # 무엇이든 채워져야
    assert isinstance(proposal.next_config, dict)
    assert "fallback" in proposal.reasoning.lower()


@pytest.mark.asyncio
async def test_novelty_recipe_works_with_empty_corpus() -> None:
    """cold-start 직후 corpus 거의 비어도 동작해야 — service에서 cold_start 우회를 안 거치고
    온 경우 (드물지만 정합 보장)."""
    llm = _MockLLM(
        '{"recipe_id": "mnist-tinymlp", '
        '"next_config": {"lr": 0.01, "batch_size": 128}, '
        '"reasoning": "base config"}'
    )
    synth = NoveltyRecipeSynthesizer(llm=llm)

    proposal = await synth.propose(corpus_recipes=[], intent="acc 올리기")

    assert proposal.recipe_id == "mnist-tinymlp"
    assert proposal.next_config["lr"] == 0.01
