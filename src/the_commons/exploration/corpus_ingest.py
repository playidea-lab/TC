"""explore-loop 결과 → TC evidence corpus best-effort 적재 (도서관·사서 갭 메우기).

R1 LID PoC 후 발견한 갭: explore-loop이 자기 로컬 archive(~/.cq/state/explore/)만 쓰고
TC의 영속 evidence corpus(PostgreSQL)·누적지식(tc_knowledge)과 분리돼 돌았다. 이 모듈이
report_result 시점에 dispatch describe를 TC /ingest로 적재해 폐루프를 닫는다.

best-effort 원칙: TC HTTP 서버(:8001) 미가동·형식 불일치·네트워크 실패 등 *모든* 예외를
조용히 삼킨다 — 적재는 corpus 누적(보너스)이고, 컨트롤러 archive(탐색 정본)는 로컬이 우선.
즉 서버 없어도 탐색은 안 깨진다.

server.py(FastMCP 인스턴스 + register 부작용)를 모듈-레벨 import하지 않는다 — 순환 회피.
JWT·설정은 server와 동일 env var를 자체적으로 읽는다(격리, 중복 최소).
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

# server와 동일 env var(격리된 자체 설정). 기본값도 server와 일치.
_TC_URL = os.getenv("TC_MCP_URL", "http://127.0.0.1:8001")
_JWT_PRIV = os.getenv("TC_MCP_JWT_PRIV", "/tmp/tc-dev/cq_priv.pem")
_CONTRIB = os.getenv("TC_MCP_CONTRIB", "explore-loop")
_JWT_ISS = os.getenv("TC_MCP_JWT_ISS", "cq.pilab.kr")
_JWT_AUD = os.getenv("TC_MCP_JWT_AUD", "the-commons")


def _issue_jwt(ttl: int = 3600) -> str:
    import jwt
    now = int(time.time())
    payload = {"sub": _CONTRIB, "iss": _JWT_ISS, "aud": _JWT_AUD,
               "iat": now, "exp": now + ttl, "origin": "internal"}
    return jwt.encode(payload, Path(_JWT_PRIV).read_bytes(), algorithm="RS256")


def _build_describe(recipe_id: str, hyperparams: dict[str, Any],
                    primary_metric: str, fitness: float,
                    diag: dict[str, Any], modality: str) -> dict[str, Any]:
    """explore action+결과 → describe_to_evidence가 먹는 최소 describe dict.

    explore의 describe(lid_eval.emit_and_describe 산출)는 pcq describe_run의 풍부한 구조가
    아니므로, 우리가 가진 정보(recipe+config+fitness+진단)로 어댑터 입력을 조립한다.
    """
    metrics = {primary_metric: float(fitness)}
    for k in ("miss_rate", "over_rate"):
        if k in diag and isinstance(diag[k], (int, float)):
            metrics[k] = float(diag[k])
    return {
        "target_metric": primary_metric,
        "best_value": float(fitness),
        "best": {"metrics": metrics},
        "reproducibility_evidence": {"config": {"hyperparams": dict(hyperparams)}},
        "fingerprint": {"modality": modality},
        "intent": {"goal": "exploration"},
    }


def try_ingest(*, recipe_id: str, hyperparams: dict[str, Any],
               primary_metric: str, fitness: float,
               diag: dict[str, Any] | None = None,
               modality: str = "vision",
               lineage_target: str | None = None) -> str | None:
    """TC corpus에 best-effort 적재. 성공 시 evidence_id, 실패(서버 미가동 등) 시 None.

    어떤 예외도 raise하지 않는다 — 호출자(report_result)는 적재 실패에 영향받지 않는다.
    """
    try:
        import asyncio

        import httpx

        from the_commons.mcp.adapter import describe_to_evidence

        desc = _build_describe(recipe_id, hyperparams, primary_metric, fitness,
                               diag or {}, modality)
        eid = f"ev-{recipe_id}-{uuid.uuid4().hex[:8]}"
        env = describe_to_evidence(
            desc, evidence_id=eid, recipe_id=recipe_id, modality=modality,
            tier="real", branch="explore", lineage_target=lineage_target,
        )

        async def _go() -> str:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(f"{_TC_URL}/ingest", json={"evidence": env},
                                 headers={"Authorization": f"Bearer {_issue_jwt()}",
                                          "Content-Type": "application/json"})
                r.raise_for_status()
                return r.json().get("evidence_id", eid)

        return asyncio.run(_go())
    except Exception:
        return None   # best-effort: 서버 미가동·형식·네트워크 모두 조용히
