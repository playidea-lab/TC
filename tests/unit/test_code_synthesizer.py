"""CodeGenSynthesizer 단위 테스트 — train.py 전체 코드 생성기.

cq-pcq-tc-dental-codegen-loop: web_search + corpus(이전 코드/결과/실패) → train.py
전체 + requirements. NextConfigProposal.generated_code/requirements를 채운다.
RR6: 생성 실패 시 직전 성공 코드 또는 최소 stub으로 degrade.
"""

from __future__ import annotations

import pytest

from the_commons.matchmaker.code_synthesizer import (
    CodeAttempt,
    CodeGenSynthesizer,
    _extract_code_block,
    _extract_requirements,
)


class _MockResponsesLLM:
    """OpenAI responses(web_search) mock — 고정 텍스트 반환."""

    def __init__(self, text: str | Exception, sources: list[str] | None = None):
        self._text = text
        self._sources = sources or []
        self.last_prompt: str | None = None

    async def generate(self, prompt: str) -> tuple[str, list[str]]:
        self.last_prompt = prompt
        if isinstance(self._text, Exception):
            raise self._text
        return self._text, self._sources


_VALID_RESP = """\
MVTec bottle anomaly detection을 위해 PatchCore 접근을 조사했습니다 (2024 SOTA).

```python
import argparse, os
p = argparse.ArgumentParser()
p.add_argument('--data-root', required=True)
a = p.parse_args()
print('@image_auroc=0.92 @pixel_auroc=0.88', flush=True)
```

requirements: ["torch", "torchvision", "scikit-learn"]
"""


@pytest.mark.asyncio
async def test_codegen_extracts_code_and_requirements() -> None:
    llm = _MockResponsesLLM(_VALID_RESP, sources=["https://arxiv.org/abs/2106.08265"])
    synth = CodeGenSynthesizer(llm=llm)
    proposal = await synth.propose(
        data_dirs=["bottle/train", "bottle/test", "bottle/ground_truth"],
        intent="MVTec bottle image_auroc 올리기",
        corpus=[],
    )
    assert proposal.generated_code is not None
    assert "argparse" in proposal.generated_code
    assert "@image_auroc=" in proposal.generated_code
    assert "torch" in proposal.requirements
    assert "scikit-learn" in proposal.requirements
    assert proposal.sources == ["https://arxiv.org/abs/2106.08265"]
    # 데이터 디렉토리 목록이 프롬프트에 흘러야 (자율 탐색 컨텍스트)
    assert "bottle/train" in (llm.last_prompt or "")


@pytest.mark.asyncio
async def test_codegen_prompt_includes_corpus_history() -> None:
    """corpus의 이전 코드/결과/실패가 프롬프트에 컨텍스트로 흘러야 한다."""
    llm = _MockResponsesLLM(_VALID_RESP)
    synth = CodeGenSynthesizer(llm=llm)
    corpus = [
        CodeAttempt(recipe_id="patchcore-v1", metrics={"image_auroc": 0.85}, failed=False, code_summary="PatchCore wide_resnet50"),
        CodeAttempt(recipe_id="ae-v1", metrics={}, failed=True, code_summary="autoencoder", error="CUDA OOM"),
    ]
    await synth.propose(data_dirs=["bottle"], intent="x", corpus=corpus)
    prompt = llm.last_prompt or ""
    assert "patchcore-v1" in prompt and "0.85" in prompt
    assert "OOM" in prompt  # 실패도 컨텍스트


@pytest.mark.asyncio
async def test_codegen_degrades_on_llm_failure() -> None:
    """LLM 실패 시 직전 성공 코드(corpus)로 degrade."""
    llm = _MockResponsesLLM(RuntimeError("web_search down"))
    synth = CodeGenSynthesizer(llm=llm)
    corpus = [
        CodeAttempt(
            recipe_id="patchcore-v1",
            metrics={"image_auroc": 0.85},
            failed=False,
            code_summary="prev",
            full_code="print('@image_auroc=0.85')",
        ),
    ]
    p = await synth.propose(data_dirs=["bottle"], intent="x", corpus=corpus)
    assert p.generated_code == "print('@image_auroc=0.85')"
    assert "fallback" in p.reasoning.lower()


@pytest.mark.asyncio
async def test_codegen_degrades_to_stub_when_no_corpus() -> None:
    """LLM 실패 + corpus 없음 → 최소 stub 코드(실행되는)."""
    llm = _MockResponsesLLM(RuntimeError("down"))
    synth = CodeGenSynthesizer(llm=llm)
    p = await synth.propose(data_dirs=["bottle"], intent="x", corpus=[])
    assert p.generated_code is not None
    assert "@image_auroc=" in p.generated_code  # 계약 준수 stub


@pytest.mark.asyncio
async def test_codegen_no_code_block_degrades() -> None:
    """응답에 코드 블록이 없으면 degrade."""
    llm = _MockResponsesLLM("코드를 못 만들겠습니다 죄송")
    synth = CodeGenSynthesizer(llm=llm)
    p = await synth.propose(data_dirs=["bottle"], intent="x", corpus=[])
    assert p.generated_code is not None  # stub
    assert "fallback" in p.reasoning.lower()


# ---------- 파서 ----------


def test_extract_code_block_fenced() -> None:
    text = "intro\n```python\nimport os\nprint('hi')\n```\noutro"
    assert _extract_code_block(text) == "import os\nprint('hi')"


def test_extract_code_block_none_when_missing() -> None:
    assert _extract_code_block("no code here") is None


def test_extract_requirements_json_list() -> None:
    text = 'requirements: ["torch", "numpy"]'
    assert _extract_requirements(text) == ["torch", "numpy"]


def test_extract_requirements_empty_when_missing() -> None:
    assert _extract_requirements("no reqs") == []
