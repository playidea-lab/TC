"""TC MCP 서버 — LLM agent가 추천·환류·적재를 MCP 도구로 직접 호출.

idea: .cq/runtime/ideas/tc-mcp-agent-interface.md

TC HTTP REST(:8001) 위의 thin layer. 각 도구는 JWT를 자동 발급해 httpx로 self
HTTP를 호출한다. tc_ingest_run만 raw 필드에서 PCQ envelope을 조립한다(agent는
sha256·integrity 보일러플레이트를 신경 쓰지 않는다). cq 디스패치는 cq mcp가,
코드 생성은 Claude Code가 — 역할 분리.

core 함수(_post_*/_get_*/build_run_envelope)는 httpx client를 주입받아 단위
테스트 가능하고, @mcp.tool() 래퍼는 client/JWT 생성만 담당한다.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import jwt
from mcp.server.fastmcp import FastMCP

from the_commons.library.content_hash import compute_integrity
from the_commons.mcp.adapter import describe_to_evidence

# 설정 — 환경변수 우선, dev 기본값(localhost) 허용
TC_URL = os.getenv("TC_MCP_URL", "http://127.0.0.1:8001")
JWT_PRIV_PATH = os.getenv("TC_MCP_JWT_PRIV", "/tmp/tc-dev/cq_priv.pem")
CONTRIB_ID = os.getenv("TC_MCP_CONTRIB", "claude-code-mcp")
JWT_ISS = os.getenv("TC_MCP_JWT_ISS", "cq.pilab.kr")
JWT_AUD = os.getenv("TC_MCP_JWT_AUD", "the-commons")

# recommend는 Gemini 직렬 호출로 느려 넉넉히, 조회/적재는 짧게
_RECOMMEND_TIMEOUT = 300.0
_DEFAULT_TIMEOUT = 60.0


# ----------------------------------------------------------------------------
# 인증 / 공통
# ----------------------------------------------------------------------------


def _issue_jwt(*, ttl_secs: int = 3600) -> str:
    now = int(time.time())
    payload = {"sub": CONTRIB_ID, "iss": JWT_ISS, "aud": JWT_AUD,
               "iat": now, "exp": now + ttl_secs, "origin": "internal"}
    return jwt.encode(payload, Path(JWT_PRIV_PATH).read_bytes(), algorithm="RS256")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _worker_spec() -> dict[str, Any]:
    return {"cpu_cores": 8, "ram_gb": 16, "gpu_model": "apple-mps", "vram_gb": 0, "has_gpu": False}


def _build_query(intent: str, modality: str, primary_metric: str, baseline: float) -> dict[str, Any]:
    """recommend query — worker_spec + data_fingerprint + intent."""
    return {
        "worker_spec": _worker_spec(),
        "data_fingerprint": {"modality": modality, "sample_count_band": "100-1k",
                             "schema_summary": {}},
        "intent": {"goal": "exploration", "description": intent,
                   "expected_baseline": {"metric": primary_metric, "value": baseline},
                   "tolerance": {"direction": "higher_is_better", "margin": 0.02}},
    }


# ----------------------------------------------------------------------------
# core (httpx client 주입 — 테스트 가능)
# ----------------------------------------------------------------------------


async def _post_recommend(client: httpx.AsyncClient, token: str, *, intent: str,
                          modality: str, primary_metric: str, baseline: float,
                          force_explore: bool, round_id: str | None) -> dict[str, Any]:
    """TC /recommend → top 방향(recipe_id + next_config + reasoning) + corpus."""
    body: dict[str, Any] = {
        "query": _build_query(intent, modality, primary_metric, baseline),
        "force_explore": force_explore,
    }
    if round_id:
        body["round_id"] = round_id
    r = await client.post(f"{TC_URL}/recommend", json=body, headers=_headers(token))
    r.raise_for_status()
    data = r.json()
    cands = data.get("candidates") or []
    top = cands[0] if cands else {}
    return {
        "recipe_id": top.get("recipe_id"),
        "next_config": top.get("next_config"),
        "reasoning": top.get("reasoning"),
        "policy": top.get("policy"),
        "corpus_context": data.get("corpus_context"),
        "alternatives": [c.get("recipe_id") for c in cands[1:]],
    }


async def _get_recent_attempts(client: httpx.AsyncClient, token: str, *, modality: str,
                               limit: int, recipe_id: str | None,
                               failed_only: bool) -> list[dict[str, Any]]:
    """TC /evidence(list) → 환류 요약 {evidence_id, recipe_id, ok, metrics, stderr_tail}.

    코드 본문은 제외(컨텍스트 절약) — 필요하면 tc_get_evidence로 on-demand.
    recipe_id/failed_only 필터는 클라이언트에서(엔드포인트 미지원)."""
    params = {"modality": modality, "limit": min(limit * 3, 100), "deprecated": "false"}
    r = await client.get(f"{TC_URL}/evidence", params=params, headers=_headers(token))
    r.raise_for_status()
    out: list[dict[str, Any]] = []
    for ev in r.json().get("evidences", []):
        pcq = ev.get("pcq_record", {})
        rid = (pcq.get("config") or {}).get("recipe_id")
        if recipe_id and rid != recipe_id:
            continue
        metrics = dict(pcq.get("metrics") or {})
        failed = bool(metrics.get("failed"))
        if failed_only and not failed:
            continue
        out.append({
            "evidence_id": ev.get("evidence_id"),
            "recipe_id": rid,
            "ok": not failed,
            "metrics": {k: v for k, v in metrics.items() if k not in ("failed", "stderr_tail")},
            "stderr_tail": metrics.get("stderr_tail"),
        })
        if len(out) >= limit:
            break
    return out


async def _get_evidence(client: httpx.AsyncClient, token: str, evidence_id: str) -> dict[str, Any]:
    """TC /evidence/{id} → 코드 본문 포함 전체 evidence (on-demand 환류 상세)."""
    r = await client.get(f"{TC_URL}/evidence/{evidence_id}", headers=_headers(token))
    r.raise_for_status()
    return r.json().get("evidence", {})


def build_run_envelope(*, evidence_id: str, recipe_id: str, code: str,
                       metrics: dict[str, Any], config: dict[str, Any] | None,
                       requirements: list[str], intent: str, modality: str,
                       data_uri: str, primary_metric: str, baseline: float,
                       lineage_target: str | None, branch: str) -> dict[str, Any]:
    """raw 필드 → PCQ envelope 조립 (agent 대신 봉투 보일러플레이트 흡수).

    next_config는 config로 들어와 PCQ config에 recipe_id와 함께 기록된다 →
    infogain within-recipe·중복 회피 가드가 살아난다."""
    code_sha = hashlib.sha256(code.encode()).hexdigest()
    pcq: dict[str, Any] = {
        "intent": {"goal": "exploration", "description": intent,
                   "expected_baseline": {"metric": primary_metric, "value": baseline},
                   "tolerance": {"direction": "higher_is_better", "margin": 0.02}},
        "data_fingerprint": {"modality": modality, "sample_count_band": "100-1k",
                             "schema_summary": {}},
        "config": {"recipe_id": recipe_id, **(config or {})},
        "metrics": metrics,
        "worker_spec": _worker_spec(),
        "attribution": {"author": {"id": CONTRIB_ID, "kind": "agent"}, "operator": CONTRIB_ID,
                        "policy": {"branch": branch, "recipe_id": recipe_id}},
        "code": {"content_sha256": code_sha, "content": code,
                 "scope": {"kind": "entry_script", "files": ["train.py"]},
                 "requirements": requirements},
        "seeds": {"main": 42, "data": "filesystem-order"},
        "data_ref": {"uri": data_uri, "content_sha256": "agent-local", "size_bytes": 0},
        "contract_version": "2.0",
    }
    pcq["integrity"] = compute_integrity(pcq)
    env: dict[str, Any] = {"evidence_id": evidence_id, "tier": "real",
                           "outreach_origin": "internal", "synthetic_source": None,
                           "pcq_record": pcq}
    if lineage_target:
        lineage_type = "exploration" if branch == "explore" else "derives_from"
        env["lineage"] = [{"type": lineage_type, "target_evidence_id": lineage_target,
                          "metadata": {"branch": branch}}]
    return env


async def _post_ingest_run(client: httpx.AsyncClient, token: str, *, envelope: dict[str, Any]) -> str:
    """조립된 envelope을 TC /ingest로 적재 → evidence_id."""
    r = await client.post(f"{TC_URL}/ingest", json={"evidence": envelope}, headers=_headers(token))
    r.raise_for_status()
    return r.json().get("evidence_id", "")


# ----------------------------------------------------------------------------
# MCP 도구 (thin wrapper — client/JWT 생성만)
# ----------------------------------------------------------------------------

mcp = FastMCP("the-commons")


@mcp.tool()
async def tc_recommend(intent: str, modality: str = "vision",
                       primary_metric: str = "image_auroc", baseline: float = 0.9,
                       force_explore: bool = False, round_id: str | None = None) -> dict[str, Any]:
    """corpus 정보이득 기반 다음 실험 방향(recipe_id + next_config + reasoning)을 추천.

    코드는 생성하지 않는다 — recipe_id를 보고 Claude Code가 train.py를 작성한다.
    force_explore=True면 corpus 밖 novelty(Gemini grounding)를 강제한다."""
    async with httpx.AsyncClient(timeout=_RECOMMEND_TIMEOUT) as c:
        return await _post_recommend(c, _issue_jwt(), intent=intent, modality=modality,
                                     primary_metric=primary_metric, baseline=baseline,
                                     force_explore=force_explore, round_id=round_id)


@mcp.tool()
async def tc_recent_attempts(modality: str = "vision", limit: int = 8,
                             recipe_id: str | None = None,
                             failed_only: bool = False) -> list[dict[str, Any]]:
    """최근 실험 시도 요약(환류) — {evidence_id, recipe_id, ok, metrics, stderr_tail}.

    self-correct: failed_only=True로 최근 실패의 traceback을 본다. 코드 본문은
    tc_get_evidence로 on-demand. recipe_id로 한 recipe 이력만 좁힐 수 있다."""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
        return await _get_recent_attempts(c, _issue_jwt(), modality=modality, limit=limit,
                                          recipe_id=recipe_id, failed_only=failed_only)


@mcp.tool()
async def tc_get_evidence(evidence_id: str) -> dict[str, Any]:
    """evidence 한 건의 전체(코드 본문 pcq.code.content 포함). 환류 2단계 — 요약을
    보고 변형/디버그할 코드를 펼칠 때 호출한다."""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
        return await _get_evidence(c, _issue_jwt(), evidence_id)


@mcp.tool()
async def tc_ingest_run(evidence_id: str, recipe_id: str, code: str, metrics: dict[str, Any],
                        intent: str, config: dict[str, Any] | None = None,
                        requirements: list[str] | None = None, modality: str = "vision",
                        data_uri: str = "file://local", primary_metric: str = "image_auroc",
                        baseline: float = 0.9, lineage_target: str | None = None,
                        branch: str = "manual") -> str:
    """실험 결과를 PCQ 계약으로 봉인해 TC에 적재 → evidence_id.

    agent는 raw 필드만 넘긴다 — sha256/integrity/data_ref는 서버가 조립한다.
    config(=recommend의 next_config)는 PCQ config에 기록되어 infogain이 읽는다."""
    env = build_run_envelope(
        evidence_id=evidence_id, recipe_id=recipe_id, code=code, metrics=metrics,
        config=config, requirements=requirements or [], intent=intent, modality=modality,
        data_uri=data_uri, primary_metric=primary_metric, baseline=baseline,
        lineage_target=lineage_target, branch=branch)
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
        return await _post_ingest_run(c, _issue_jwt(), envelope=env)


@mcp.tool()
async def tc_ingest_pcq(describe: dict[str, Any], recipe_id: str,
                        evidence_id: str | None = None, modality: str = "vision",
                        sample_count_band: str = "100-1k",
                        lineage_target: str | None = None, branch: str = "manual") -> str:
    """pcq `describe_run` 결과를 TC에 적재 → evidence_id (pcq 정본 경로).

    pcq가 만든 계약(describe)을 받아 TC evidence로 변환·저장한다 — agent는 봉투를
    조립하지 않고 pcq가 만든 것을 그대로 넘긴다. config의 hyperparams 본문(P5)이
    within_synth로 흐른다. evidence_id 미지정 시 자동 생성. (raw 경로는 tc_ingest_run)"""
    eid = evidence_id or f"ev-{recipe_id}-{uuid.uuid4().hex[:8]}"
    env = describe_to_evidence(describe, evidence_id=eid, recipe_id=recipe_id,
                               modality=modality, sample_count_band=sample_count_band,
                               lineage_target=lineage_target, branch=branch)
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
        return await _post_ingest_run(c, _issue_jwt(), envelope=env)


def main() -> None:
    """stdio MCP 서버 기동 (cq mcp와 같은 패턴)."""
    mcp.run()


if __name__ == "__main__":
    main()
