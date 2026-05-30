"""cq MCP stdio JSON-RPC 클라이언트 + 결과 stdout 파서.

cq-ops/skills/explore-loop/scripts/cq_dispatch.py에서 CqMcpClient·parse_metrics만 추출 이동
(R1 사서 통합, 2026-05-28). 원본의 build_command·read_run_log·cmd_dispatch CLI·`.dispatch`
멀티스텝 메서드는 mvtec-특화라 가져오지 않음 — LocalWorker.submit이 동일 흐름을 직접 조립한다.

이 모듈은 dispatcher 패키지 내부 의존이며 외부에서 직접 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# 설정 (환경값 우선) — 워크스페이스 기본 ~/.cq/workspace, cq 바이너리는 PATH의 cq.
CQ_BIN = os.environ.get("CQ_BIN") or shutil.which("cq") or "cq"
WORKSPACE_ROOT = Path(os.environ.get("CQ_WORKSPACE_ROOT", str(Path.home() / ".cq" / "workspace")))

METRIC_RE = re.compile(r"@([a-zA-Z_][a-zA-Z0-9_]*)=([-+0-9.eE]+)")


class CqMcpClient:
    """cq mcp 서버를 stdio subprocess로 띄우고 JSON-RPC로 도구 호출."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            [CQ_BIN, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "the-commons-dispatcher", "version": "1"},
        })
        self._notify("notifications/initialized", {})

    def _rpc(self, method: str, params: dict, *, max_lines: int = 800) -> dict | None:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        assert self._proc.stdin
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()
        assert self._proc.stdout
        for _ in range(max_lines):
            line = self._proc.stdout.readline()
            if not line:
                return None
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == self._id:
                return m
        return None

    def _notify(self, method: str, params: dict) -> None:
        assert self._proc.stdin
        self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self._proc.stdin.flush()

    # cq MCP 도구명이 v1.0.2x에서 snake_case → "Title Case"로 바뀜(2026-05-29).
    # 호출부(local/remote worker)는 옛 이름을 쓰고, 여기서 새 이름으로 변환(단일 지점).
    _TOOL_ALIAS = {
        "create_job": "Create job",
        "create_run": "Create run",
        "control_job": "Control job",
        "write_file": "Worker write",
        "read_file": "Worker read",
        "get_status": "Get job",
        "get_worker": "Get worker",
    }

    def call(self, name: str, args: dict) -> str:
        tool = self._TOOL_ALIAS.get(name, name)
        r = self._rpc("tools/call", {"name": tool, "arguments": args})
        content = (r or {}).get("result", {}).get("content", [])
        return content[0]["text"] if content else json.dumps(r)

    def close(self) -> None:
        self._proc.terminate()

    def poll(self, job_id: str, *, run_timeout: int) -> str:
        """get_status 폴링. 최종 상태 텍스트 반환."""
        deadline = time.time() + run_timeout
        last = ""
        while time.time() < deadline:
            time.sleep(8)
            last = self.call("get_status", {"job_id": job_id})   # → "Get job"(별칭)
            s = (re.search(r"status:\s*(\w+)", last) or [None, "?"])[1]
            if s in ("SUCCEEDED", "FAILED", "COMPLETED", "ERROR", "CANCELLED"):
                return last
        return last + "\n[TIMEOUT]"


def parse_metrics(status_text: str) -> tuple[dict, bool]:
    """get_status 텍스트에서 metrics + 성공 여부 파싱."""
    succeeded = bool(re.search(r"status:\s*(SUCCEEDED|COMPLETED)", status_text))
    metrics: dict = {}
    mjson = re.search(r"metrics.*?:\s*(\{[^}]*\})", status_text, re.DOTALL)
    if mjson:
        try:
            metrics = json.loads(mjson.group(1))
        except json.JSONDecodeError:
            pass
    if not metrics:
        for k, v in METRIC_RE.findall(status_text):
            try:
                metrics[k] = float(v)
            except ValueError:
                pass
    if not succeeded:
        metrics["failed"] = True
    return metrics, succeeded
