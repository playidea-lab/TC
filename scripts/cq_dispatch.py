"""cq 디스패치 + PCQ 봉인 + TC 적재 — 코드는 이 세션의 Claude Code가 주입한다.

cq의 본래 모델: 코드 생성 주체는 "지금 사용 중인 LLM"(Claude Code)이고, 이 모듈은
그 코드를 원격 워커에 디스패치하고 PCQ 계약으로 봉인해 TC 도서관에 적재한다.
반복(폐루프)은 Claude Code의 /loop·/goal 슬래시 명령이 담당한다 — 별도 무인
wrapper도, TC가 API 키로 코드를 생성하던 /codegen도 쓰지 않는다.

서브커맨드:
  recommend   TC /recommend로 다음 실험 방향(recipe_id + next_config) 조회 → 내가 코드 작성
  run         내가 작성한 train.py를 cq로 디스패치 → 실행 → PCQ 봉인 → TC ingest → evidence_id

흐름 (1 사이클):
  1. (recommend) TC 소믈리에에게 corpus 정보이득 기반 방향을 받는다
  2. Claude Code가 그 방향으로 train.py를 작성한다 (이 모듈 밖)
  3. (run) cq mcp stdio JSON-RPC: create_job → create_run → write_file → control_job(start) → poll
  4. @metric= 파싱 / 실패 traceback 회수
  5. PCQ envelope(code vendoring + sha256) → POST /ingest → evidence_id
  6. state 갱신 (best/성공률/lineage)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

# ----------------------------------------------------------------------------
# 설정 (현재 노트북 워커 + MVTec bottle 기본값 — 다른 실험은 ExperimentSpec override)
# ----------------------------------------------------------------------------

CQ_BIN = "/Users/changmin/.local/bin/cq"
PROJECT_ID = "2f285d78-927f-4ad6-9fe8-1159915780f4"  # cq_test
WORKER_ID = "37f67d0d-5c41-4e9d-b30b-7ae7ddd4f836"  # my-notebook
WORKSPACE_ROOT = Path("/Users/changmin/.cq/workspace")
DATA_ROOT = "/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection"
CATEGORY = "bottle"
TC_URL = "http://127.0.0.1:8001"
JWT_PRIV = Path("/tmp/tc-dev/cq_priv.pem")
JWT_ISS, JWT_AUD, CONTRIB_ID = "cq.pilab.kr", "the-commons", "claude-code-loop"
STATE_FILE = Path(__file__).parent.parent / ".cq" / "runtime" / "state" / "cq_loop_state.json"
DEFAULT_INTENT = "MVTec bottle 이미지/픽셀 이상탐지 AUROC 최대화"

# cq 하네스 PATH에 uv 없음 → command 안에서 export (M0에서 확정)
CMD_PREFIX = 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH" && uv run --no-project'

METRIC_RE = re.compile(r"@([a-zA-Z_][a-zA-Z0-9_]*)=([-+0-9.eE]+)")
_REQ_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


# ----------------------------------------------------------------------------
# 실험 스펙 — recommend query와 PCQ envelope이 공유하는 메타
# ----------------------------------------------------------------------------


@dataclass
class ExperimentSpec:
    """한 실험의 메타. worker_spec/data_fingerprint/intent를 recommend query와
    envelope이 공유한다 (같은 PCQ 부품). 데이터셋이 바뀌면 이 값만 바꾼다."""

    recipe_id: str
    intent: str = DEFAULT_INTENT
    requirements: list[str] = field(default_factory=list)
    metrics_keys: list[str] = field(default_factory=lambda: ["image_auroc", "pixel_auroc"])
    primary_metric: str = "image_auroc"
    baseline_value: float = 0.9
    modality: str = "vision"
    sample_band: str = "100-1k"
    data_uri: str = f"file://{DATA_ROOT}/{CATEGORY}"
    data_sha: str = "mvtec-bottle-local"
    data_size: int = 157_286_400
    schema_summary: dict[str, Any] = field(default_factory=lambda: {"dataset": "mvtec-bottle"})


def _worker_spec() -> dict[str, Any]:
    """현재 워커(노트북, Apple MPS) 스펙."""
    return {"cpu_cores": 8, "ram_gb": 16, "gpu_model": "apple-mps", "vram_gb": 0, "has_gpu": False}


def _data_fingerprint(spec: ExperimentSpec) -> dict[str, Any]:
    return {"modality": spec.modality, "sample_count_band": spec.sample_band,
            "schema_summary": spec.schema_summary}


def _intent_block(spec: ExperimentSpec) -> dict[str, Any]:
    return {"goal": "exploration", "description": spec.intent,
            "expected_baseline": {"metric": spec.primary_metric, "value": spec.baseline_value},
            "tolerance": {"direction": "higher_is_better", "margin": 0.02}}


def build_command(spec: ExperimentSpec) -> str:
    """워커 실행 커맨드. stdout(@metric)은 cq metric writer로 직접, stderr(traceback)만
    train_err.log로 분리 — tee/파이프는 metric 파싱을 막으므로 2>만 쓴다."""
    with_flags = " ".join(f"--with {r}" for r in spec.requirements if _REQ_RE.match(r))
    return f"{CMD_PREFIX} {with_flags} python -u train.py --data-root {DATA_ROOT} 2> train_err.log"


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

    def read_run_log(self, job_id: str, *, tail_chars: int = 2500) -> str:
        """워크스페이스 train_err.log 회수 (실패 traceback 환류용). 노트북 로컬 직접 읽기."""
        p = WORKSPACE_ROOT / job_id / "train_err.log"
        try:
            if p.exists():
                return p.read_text(errors="replace")[-tail_chars:]
        except OSError:
            pass
        return ""


# ----------------------------------------------------------------------------
# TC HTTP
# ----------------------------------------------------------------------------


def issue_jwt(*, ttl_secs: int = 28_800) -> str:
    now = int(time.time())
    payload = {"sub": CONTRIB_ID, "iss": JWT_ISS, "aud": JWT_AUD,
               "iat": now, "exp": now + ttl_secs, "origin": "internal"}
    return jwt.encode(payload, JWT_PRIV.read_bytes(), algorithm="RS256")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def call_recommend(client: httpx.Client, token: str, tc_url: str, spec: ExperimentSpec,
                   *, round_id: str | None = None, force_explore: bool = False) -> dict[str, Any]:
    """TC /recommend — 다음 실험 방향(recipe_id + next_config) 조회. 코드 생성은 안 한다."""
    query = {"worker_spec": _worker_spec(), "data_fingerprint": _data_fingerprint(spec),
             "intent": _intent_block(spec)}
    body: dict[str, Any] = {"query": query, "force_explore": force_explore}
    if round_id:
        body["round_id"] = round_id
    r = client.post(f"{tc_url}/recommend", json=body, headers=_headers(token), timeout=120.0)
    r.raise_for_status()
    return r.json()


def call_ingest(client: httpx.Client, token: str, tc_url: str, envelope: dict[str, Any]) -> bool:
    try:
        r = client.post(f"{tc_url}/ingest", json={"evidence": envelope},
                        headers=_headers(token), timeout=30.0)
    except httpx.HTTPError as exc:
        print(f"  ⚠ ingest 네트워크 오류: {exc}", flush=True)
        return False
    if r.status_code >= 400:
        print(f"  ⚠ ingest {r.status_code}: {r.text[:300]}", flush=True)
        return False
    return True


# ----------------------------------------------------------------------------
# PCQ envelope (코드 vendoring)
# ----------------------------------------------------------------------------


def build_envelope(*, evidence_id: str, spec: ExperimentSpec, code: str, metrics: dict[str, Any],
                   sources: list[str], policy_meta: dict[str, Any],
                   lineage_type: str | None, lineage_target: str | None) -> dict[str, Any]:
    """생성 train.py를 PCQ 계약으로 봉인. code vendoring(본문 + sha256)으로 재현·감사 단위."""
    from the_commons.library.content_hash import compute_integrity

    code_sha = hashlib.sha256(code.encode()).hexdigest()
    attribution: dict[str, Any] = {"author": {"id": "claude-code", "kind": "agent"},
                                   "operator": CONTRIB_ID, "policy": policy_meta}
    if sources:
        attribution["sources"] = sources
    pcq: dict[str, Any] = {
        "intent": _intent_block(spec),
        "data_fingerprint": _data_fingerprint(spec),
        "config": {"recipe_id": spec.recipe_id},
        "metrics": metrics,
        "worker_spec": _worker_spec(),
        "attribution": attribution,
        "code": {"content_sha256": code_sha, "content": code,
                 "scope": {"kind": "entry_script", "files": ["train.py"]},
                 "requirements": spec.requirements},
        "seeds": {"main": 42, "data": "filesystem-order"},
        "data_ref": {"uri": spec.data_uri, "content_sha256": spec.data_sha, "size_bytes": spec.data_size},
        "contract_version": "2.0",
    }
    pcq["integrity"] = compute_integrity(pcq)
    env: dict[str, Any] = {"evidence_id": evidence_id, "tier": "real",
                           "outreach_origin": "internal", "synthetic_source": None, "pcq_record": pcq}
    if lineage_type and lineage_target:
        env["lineage"] = [{"type": lineage_type, "target_evidence_id": lineage_target,
                          "metadata": {"branch": policy_meta.get("branch")}}]
    return env


# ----------------------------------------------------------------------------
# 영속 state
# ----------------------------------------------------------------------------


@dataclass
class LoopState:
    last_round: int = 0
    last_evidence_id: str | None = None
    best_evidence_id: str | None = None
    best_metric: float | None = None
    n_success: int = 0
    n_fail: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, p: Path) -> LoopState:
        if not p.exists():
            return cls()
        d = json.loads(p.read_text())
        return cls(d.get("last_round", 0), d.get("last_evidence_id"), d.get("best_evidence_id"),
                   d.get("best_metric"), d.get("n_success", 0), d.get("n_fail", 0), d.get("history", []))

    def save(self, p: Path) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "last_round": self.last_round, "last_evidence_id": self.last_evidence_id,
            "best_evidence_id": self.best_evidence_id, "best_metric": self.best_metric,
            "n_success": self.n_success, "n_fail": self.n_fail, "history": self.history[-50:],
        }, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_metrics(status_text: str) -> tuple[dict[str, Any], bool]:
    """get_status 텍스트에서 metrics + 성공 여부 파싱."""
    succeeded = bool(re.search(r"status:\s*(SUCCEEDED|COMPLETED)", status_text))
    metrics: dict[str, Any] = {}
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
        err = re.search(r'error="([^"]+)"', status_text)
        if err:
            metrics["stderr_tail"] = err.group(1)[:300]
    return metrics, succeeded


# ----------------------------------------------------------------------------
# 1 사이클 — 코드는 인자로 받는다 (생성은 Claude Code)
# ----------------------------------------------------------------------------


def run_cycle(cq: CqMcpClient, http: httpx.Client, token: str, tc_url: str, *,
              code: str, spec: ExperimentSpec, state: LoopState, run_timeout: int,
              branch: str = "manual") -> tuple[str | None, dict[str, Any], bool]:
    """train.py 1건을 cq로 디스패치 → 실행 → PCQ 봉인 → TC ingest. (evidence_id, metrics, ok)."""
    rnd = state.last_round + 1
    command = build_command(spec)
    jid = cq.dispatch(name=f"{spec.recipe_id}-r{rnd:04d}", command=command, code=code,
                      requirements=spec.requirements, metrics_keys=spec.metrics_keys)
    status = cq.poll(jid, run_timeout=run_timeout)
    metrics, ok = parse_metrics(status)
    if not ok:
        log_tail = cq.read_run_log(jid)
        if log_tail:
            metrics["stderr_tail"] = log_tail
    print(f"  ← run: job={jid} ok={ok} metrics_keys={list(metrics.keys())}", flush=True)

    eid = f"ev-{spec.recipe_id}-{rnd:04d}-{uuid.uuid4().hex[:6]}"
    lt, ltarget = ("derives_from", state.last_evidence_id) if state.last_evidence_id else (None, None)
    policy_meta = {"branch": branch, "round_id": f"r{rnd}", "recipe_id": spec.recipe_id}
    env = build_envelope(evidence_id=eid, spec=spec, code=code, metrics=metrics, sources=[],
                         policy_meta=policy_meta, lineage_type=lt, lineage_target=ltarget)
    if not call_ingest(http, token, tc_url, env):
        print("  ↷ ingest 실패 → state 갱신 없음", flush=True)
        return None, metrics, ok

    _update_state(state, rnd, eid, spec.primary_metric, metrics, ok)
    print(f"  → ingest: {eid}", flush=True)
    return eid, metrics, ok


def _update_state(state: LoopState, rnd: int, eid: str, primary: str,
                  metrics: dict[str, Any], ok: bool) -> None:
    val = metrics.get(primary)
    if ok:
        state.n_success += 1
    else:
        state.n_fail += 1
    if ok and isinstance(val, int | float) and (state.best_metric is None or val > state.best_metric):
        state.best_metric = float(val)
        state.best_evidence_id = eid
        print(f"  ★ new best {primary}={val}", flush=True)
    state.last_round = rnd
    state.last_evidence_id = eid
    state.history.append({"round": rnd, "evidence_id": eid, "recipe_id": eid.split("-")[1],
                          "ok": ok, "metrics": metrics, "ts": datetime.now(timezone.utc).isoformat()})
    state.save(STATE_FILE)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def _spec_from_args(args: argparse.Namespace) -> ExperimentSpec:
    kwargs: dict[str, Any] = {"recipe_id": args.recipe, "requirements": args.req or []}
    if getattr(args, "intent", None):
        kwargs["intent"] = args.intent
    if getattr(args, "metric", None):
        kwargs["metrics_keys"] = args.metric
        kwargs["primary_metric"] = args.metric[0]
    return ExperimentSpec(**kwargs)


def cmd_recommend(args: argparse.Namespace) -> int:
    """TC 방향 추천 조회 → JSON 출력. 이걸 보고 Claude Code가 train.py를 작성한다."""
    spec = _spec_from_args(args)
    token = issue_jwt()
    with httpx.Client() as http:
        rec = call_recommend(http, token, args.tc_url, spec,
                             round_id=args.round_id, force_explore=args.force_explore)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """내가 작성한 train.py를 cq로 디스패치 → PCQ 봉인 → TC ingest → evidence_id 출력."""
    code = Path(args.code).read_text(encoding="utf-8")
    spec = _spec_from_args(args)
    state = LoopState.load(STATE_FILE)
    token = issue_jwt()
    cq = CqMcpClient()
    try:
        with httpx.Client() as http:
            eid, _metrics, ok = run_cycle(cq, http, token, args.tc_url, code=code, spec=spec,
                                          state=state, run_timeout=args.run_timeout, branch=args.branch)
    finally:
        cq.close()
    total = state.n_success + state.n_fail
    rate = state.n_success / total if total else 0
    print(f"\n📊 round={state.last_round} ok={ok} evidence={eid} "
          f"성공률={rate:.0%} ({state.n_success}/{total}) best_{spec.primary_metric}={state.best_metric}",
          flush=True)
    return 0 if eid else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="cq 디스패치 + PCQ 봉인 + TC 적재 (코드는 Claude Code가 주입)")
    ap.add_argument("--tc-url", default=TC_URL)
    sub = ap.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("recommend", help="TC 방향 추천 조회")
    rec.add_argument("--recipe", default="experiment", help="query recipe 힌트 (방향 조회엔 영향 적음)")
    rec.add_argument("--intent")
    rec.add_argument("--metric", action="append")
    rec.add_argument("--req", action="append")
    rec.add_argument("--round-id", dest="round_id")
    rec.add_argument("--force-explore", action="store_true")
    rec.set_defaults(func=cmd_recommend)

    run = sub.add_parser("run", help="train.py 디스패치 → PCQ → ingest")
    run.add_argument("--code", required=True, help="Claude Code가 작성한 train.py 경로")
    run.add_argument("--recipe", required=True, help="recipe_id (예: patchcore)")
    run.add_argument("--intent")
    run.add_argument("--metric", action="append", help="cq 회수 메트릭 (다중). 첫 값이 best 판정 기준")
    run.add_argument("--req", action="append", help="pip requirement (다중)")
    run.add_argument("--branch", default="manual", help="lineage 분기 라벨 (exploit/explore/manual)")
    run.add_argument("--run-timeout", type=int, default=1200)
    run.set_defaults(func=cmd_run)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
