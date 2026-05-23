"""cq 코드 디스패치 헬퍼 — 코드를 원격 워커에 올려 실행하고 결과를 회수한다.

역할 분리: 추천·적재는 the-commons MCP(tc_recommend / tc_ingest_pcq), 코드 생성은
Claude Code, 코드 디스패치는 이 모듈. cq mcp stdio JSON-RPC로
create_job→create_run→write_file→control_job(start)→poll 절차를 묶어 agent가 매번
5단계를 호출하지 않게 한다.

TC(recommend/ingest)·PCQ 봉인은 여기 없다 — 결과(metrics/workspace)를 stdout JSON으로
반환하고, 적재는 agent가 워커 workspace의 pcq run record를 the-commons.tc_ingest_pcq로
넘겨 수행한다(정본 경로). 균열 A 일원화로 raw envelope 조립·TC 호출은 제거됨.

흐름:
  1. Claude Code가 train.py 작성(pcq.config/log_config 규약)
  2. (이 모듈) cq로 워커에 디스패치 → 실행 → @metric / stderr 회수 → stdout JSON
  3. agent가 workspace에서 pcq describe_run → tc_ingest_pcq로 적재
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# ----------------------------------------------------------------------------
# 설정 (현재 노트북 워커 기본값 — --data-root 등으로 override)
# ----------------------------------------------------------------------------

CQ_BIN = "/Users/changmin/.local/bin/cq"
PROJECT_ID = "2f285d78-927f-4ad6-9fe8-1159915780f4"  # cq_test
WORKER_ID = "37f67d0d-5c41-4e9d-b30b-7ae7ddd4f836"  # my-notebook
WORKSPACE_ROOT = Path("/Users/changmin/.cq/workspace")
DATA_ROOT = "/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection"

# cq 하네스 PATH에 uv 없음 → command 안에서 export (M0에서 확정)
CMD_PREFIX = 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH" && uv run --no-project'

METRIC_RE = re.compile(r"@([a-zA-Z_][a-zA-Z0-9_]*)=([-+0-9.eE]+)")
_REQ_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def build_command(requirements: list[str], data_root: str) -> str:
    """워커 실행 커맨드. stdout(@metric)은 cq metric writer로 직접, stderr(traceback)만
    train_err.log로 분리 — tee/파이프는 metric 파싱을 막으므로 2>만 쓴다."""
    with_flags = " ".join(f"--with {r}" for r in requirements if _REQ_RE.match(r))
    return f"{CMD_PREFIX} {with_flags} python -u train.py --data-root {data_root} 2> train_err.log"


def read_run_log(job_id: str, *, tail_chars: int = 2500) -> str:
    """워크스페이스 train_err.log 회수 (실패 traceback). 노트북 로컬 직접 읽기."""
    p = WORKSPACE_ROOT / job_id / "train_err.log"
    try:
        if p.exists():
            return p.read_text(errors="replace")[-tail_chars:]
    except OSError:
        pass
    return ""


# ----------------------------------------------------------------------------
# cq mcp stdio JSON-RPC 클라이언트
# ----------------------------------------------------------------------------


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
            "clientInfo": {"name": "cq-dispatch", "version": "1"},
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

    def call(self, name: str, args: dict) -> str:
        r = self._rpc("tools/call", {"name": name, "arguments": args})
        content = (r or {}).get("result", {}).get("content", [])
        return content[0]["text"] if content else json.dumps(r)

    def close(self) -> None:
        self._proc.terminate()

    def dispatch(self, *, name: str, command: str, code: str,
                 requirements: list[str], metrics_keys: list[str]) -> str:
        """create_job → create_run → write_file → control_job(start). job_id 반환.

        write_file(NATS)는 노트북 워커에서 불안정 → 로컬 파일 직접 쓰기로 fallback
        (wrapper=워커=노트북 로컬이라 가능). NATS RPC 우회."""
        cj = self.call("create_job", {
            "project_id": PROJECT_ID, "name": name, "command": command,
            "config": json.dumps({"metrics": metrics_keys, "requirements": requirements}),
        })
        m = re.search(r"([0-9a-f-]{36})", cj)
        if not m:
            raise RuntimeError(f"create_job 실패: {cj[:200]}")
        jid = m.group(1)
        self.call("create_run", {"job_id": jid, "worker_id": WORKER_ID})
        ws_dir = WORKSPACE_ROOT / jid
        ws = str(ws_dir / "train.py")
        self.call("write_file", {"worker_id": WORKER_ID, "path": ws, "content": code})
        local = ws_dir / "train.py"
        if not local.exists() or local.read_text(errors="replace") != code:
            ws_dir.mkdir(parents=True, exist_ok=True)
            local.write_text(code, encoding="utf-8")
        self.call("control_job", {"action": "start", "job_id": jid, "worker_id": WORKER_ID})
        return jid

    def poll(self, job_id: str, *, run_timeout: int) -> str:
        """get_status 폴링. 최종 상태 텍스트 반환."""
        deadline = time.time() + run_timeout
        last = ""
        while time.time() < deadline:
            time.sleep(8)
            last = self.call("get_status", {"resource": "job", "id": job_id})
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


# ----------------------------------------------------------------------------
# CLI — 디스패치 + 결과 stdout (적재는 agent가 the-commons.tc_ingest_pcq로)
# ----------------------------------------------------------------------------


def cmd_dispatch(args: argparse.Namespace) -> int:
    """train.py를 cq로 디스패치 → 실행 → 결과 JSON stdout.

    출력의 workspace에서 agent가 pcq describe_run을 읽어 tc_ingest_pcq로 적재한다.
    """
    code = Path(args.code).read_text(encoding="utf-8")
    command = build_command(args.req or [], args.data_root)
    cq = CqMcpClient()
    try:
        jid = cq.dispatch(name=f"{args.recipe}-{int(time.time())}", command=command,
                          code=code, requirements=args.req or [], metrics_keys=args.metric or [])
        status = cq.poll(jid, run_timeout=args.run_timeout)
    finally:
        cq.close()
    metrics, ok = parse_metrics(status)
    if not ok:
        tail = read_run_log(jid)
        if tail:
            metrics["stderr_tail"] = tail
    out = {"job_id": jid, "ok": ok, "metrics": metrics,
           "workspace": str(WORKSPACE_ROOT / jid)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="cq 코드 디스패치 헬퍼 (추천·적재는 the-commons MCP, 코드는 Claude Code)")
    ap.add_argument("--code", required=True, help="Claude Code가 작성한 train.py 경로")
    ap.add_argument("--recipe", required=True, help="job 이름 prefix (예: patchcore)")
    ap.add_argument("--metric", action="append", help="cq 회수 메트릭 (다중)")
    ap.add_argument("--req", action="append", help="pip requirement (다중)")
    ap.add_argument("--data-root", default=DATA_ROOT, help="워커 train.py --data-root")
    ap.add_argument("--run-timeout", type=int, default=1200)
    return cmd_dispatch(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
