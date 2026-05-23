"""TC MCP 서버 core 함수 단위 테스트 — httpx MockTransport로 HTTP mock.

도구 wrapper(@mcp.tool())는 client/JWT 생성만 하는 thin layer라, 로직은 core
함수(_post_*/_get_*/build_run_envelope)에서 검증한다. JWT는 token 인자 주입이라
priv key 없이 테스트 가능.
"""

from __future__ import annotations

import json

import httpx

from the_commons.mcp.server import (
    _get_evidence,
    _get_recent_attempts,
    _post_ingest_run,
    _post_recommend,
    build_run_envelope,
)


def _client(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- recommend ----------


async def test_recommend_extracts_top_direction() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/recommend"
        return httpx.Response(200, json={
            "candidates": [
                {"recipe_id": "patchcore", "next_config": {"lr": 0.001},
                 "reasoning": "top", "policy": {"branch": "exploit"}},
                {"recipe_id": "efficientad"},
            ],
            "corpus_context": {"real_count": 20, "synthetic_count": 0},
        })

    async with _client(handler) as c:
        out = await _post_recommend(c, "t", intent="x", modality="vision",
                                    primary_metric="image_auroc", baseline=0.9,
                                    force_explore=False, round_id=None)
    assert out["recipe_id"] == "patchcore"
    assert out["next_config"] == {"lr": 0.001}
    assert out["alternatives"] == ["efficientad"]
    assert out["corpus_context"]["real_count"] == 20


async def test_recommend_empty_candidates_safe() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [], "corpus_context": {"real_count": 0}})

    async with _client(handler) as c:
        out = await _post_recommend(c, "t", intent="x", modality="vision",
                                    primary_metric="image_auroc", baseline=0.9,
                                    force_explore=False, round_id=None)
    assert out["recipe_id"] is None  # 빈 corpus에도 안전


# ---------- recent_attempts (환류) ----------


def _ev(eid: str, recipe: str, *, failed: bool = False, auc: float = 0.8) -> dict:
    metrics = {"failed": True, "stderr_tail": "ModuleNotFound: torch"} if failed else {"image_auroc": auc}
    return {"evidence_id": eid, "pcq_record": {"config": {"recipe_id": recipe}, "metrics": metrics}}


async def test_recent_attempts_failed_only_filters() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"evidences": [
            _ev("ev-1", "rf", auc=0.8),
            _ev("ev-2", "xgb", failed=True),
        ], "total": 2, "limit": 20, "offset": 0})

    async with _client(handler) as c:
        out = await _get_recent_attempts(c, "t", modality="vision", limit=8,
                                         recipe_id=None, failed_only=True)
    assert len(out) == 1
    assert out[0]["evidence_id"] == "ev-2"
    assert out[0]["ok"] is False
    assert "ModuleNotFound" in out[0]["stderr_tail"]


async def test_recent_attempts_recipe_filter() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"evidences": [
            _ev("ev-1", "rf"), _ev("ev-2", "xgb"),
        ], "total": 2, "limit": 20, "offset": 0})

    async with _client(handler) as c:
        out = await _get_recent_attempts(c, "t", modality="vision", limit=8,
                                         recipe_id="xgb", failed_only=False)
    assert len(out) == 1
    assert out[0]["recipe_id"] == "xgb"
    assert "failed" not in out[0]["metrics"]  # 요약 metrics에서 failed/stderr 제외


# ---------- get_evidence ----------


async def test_get_evidence_returns_full_with_code() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/evidence/ev-x"
        return httpx.Response(200, json={"evidence": {
            "evidence_id": "ev-x",
            "pcq_record": {"code": {"content": "print('@image_auroc=0.8')"}},
        }})

    async with _client(handler) as c:
        ev = await _get_evidence(c, "t", "ev-x")
    assert ev["pcq_record"]["code"]["content"] == "print('@image_auroc=0.8')"


# ---------- build_run_envelope (순수) ----------


def test_build_envelope_records_next_config_in_pcq_config() -> None:
    env = build_run_envelope(
        evidence_id="ev-1", recipe_id="patchcore", code="print('@image_auroc=0.8')",
        metrics={"image_auroc": 0.8}, config={"lr": 0.001, "backbone": "wresnet50"},
        requirements=["torch"], intent="x", modality="vision", data_uri="file://d",
        primary_metric="image_auroc", baseline=0.9, lineage_target=None, branch="exploit")
    cfg = env["pcq_record"]["config"]
    assert cfg["recipe_id"] == "patchcore"
    assert cfg["lr"] == 0.001  # next_config가 PCQ config에 기록
    assert cfg["backbone"] == "wresnet50"
    assert env["pcq_record"]["integrity"]["content_hash"]
    assert env["pcq_record"]["code"]["content_sha256"]
    assert env["tier"] == "real"


def test_build_envelope_explore_lineage_is_exploration() -> None:
    env = build_run_envelope(
        evidence_id="ev-2", recipe_id="ddad", code="x", metrics={}, config=None,
        requirements=[], intent="x", modality="vision", data_uri="file://d",
        primary_metric="image_auroc", baseline=0.9, lineage_target="ev-1", branch="explore")
    assert env["lineage"][0]["type"] == "exploration"
    assert env["lineage"][0]["target_evidence_id"] == "ev-1"


def test_build_envelope_exploit_lineage_is_derives_from() -> None:
    env = build_run_envelope(
        evidence_id="ev-3", recipe_id="patchcore", code="x", metrics={}, config=None,
        requirements=[], intent="x", modality="vision", data_uri="file://d",
        primary_metric="image_auroc", baseline=0.9, lineage_target="ev-1", branch="exploit")
    assert env["lineage"][0]["type"] == "derives_from"


def test_build_envelope_no_lineage_target_omits_lineage() -> None:
    env = build_run_envelope(
        evidence_id="ev-4", recipe_id="patchcore", code="x", metrics={}, config=None,
        requirements=[], intent="x", modality="vision", data_uri="file://d",
        primary_metric="image_auroc", baseline=0.9, lineage_target=None, branch="manual")
    assert "lineage" not in env


# ---------- ingest_run ----------


async def test_ingest_run_posts_envelope_returns_id() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["body"] = json.loads(req.content)
        return httpx.Response(201, json={"evidence_id": "ev-new", "tier": "real"})

    env = build_run_envelope(
        evidence_id="ev-new", recipe_id="patchcore", code="x", metrics={"image_auroc": 0.8},
        config={"lr": 0.001}, requirements=[], intent="x", modality="vision", data_uri="file://d",
        primary_metric="image_auroc", baseline=0.9, lineage_target=None, branch="manual")
    async with _client(handler) as c:
        eid = await _post_ingest_run(c, "t", envelope=env)
    assert eid == "ev-new"
    assert captured["path"] == "/ingest"
    assert captured["body"]["evidence"]["pcq_record"]["config"]["lr"] == 0.001
