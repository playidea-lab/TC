"""TC MCP 서버 core 함수 단위 테스트 — httpx MockTransport로 HTTP mock.

도구 wrapper(@mcp.tool())는 client/JWT 생성만 하는 thin layer라, 로직은 core
함수(_post_*/_get_*)에서 검증한다. envelope 조립은 어댑터 영역이라 test_mcp_adapter.py.
JWT는 token 인자 주입이라 priv key 없이 테스트 가능.
"""

from __future__ import annotations

import json

import httpx

from the_commons.mcp.server import (
    _get_evidence,
    _get_recent_attempts,
    _post_ingest_run,
    _post_recommend,
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


# ---------- _post_ingest_run (envelope POST — 조립은 adapter 영역) ----------


async def test_post_ingest_run_posts_envelope_returns_id() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["body"] = json.loads(req.content)
        return httpx.Response(201, json={"evidence_id": "ev-new", "tier": "real"})

    env = {"evidence_id": "ev-new", "tier": "real",
           "pcq_record": {"config": {"recipe_id": "patchcore", "lr": 0.001}}}
    async with _client(handler) as c:
        eid = await _post_ingest_run(c, "t", envelope=env)
    assert eid == "ev-new"
    assert captured["path"] == "/ingest"
    assert captured["body"]["evidence"]["pcq_record"]["config"]["lr"] == 0.001
