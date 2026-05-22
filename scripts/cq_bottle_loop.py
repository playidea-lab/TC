"""cq-pcq-tc-dental-codegen-loop — MVTec bottle anomaly detection 자율 코드생성 폐루프.

idea: `.cq/runtime/ideas/cq-pcq-tc-dental-codegen-loop.md`

흐름 (매 round):
  1. POST {TC}/codegen (data_dirs + intent) → TC 소믈리에가 web_search + corpus 환류로
     train.py 전체 + requirements 생성
  2. cq mcp stdio JSON-RPC로 4090/노트북 워커에 디스패치:
     create_job → create_run → write_file(생성 코드) → control_job(start) → get_status 폴링
  3. @image_auroc= @pixel_auroc= 파싱 (성공) / 실패 마커 (FAILED)
  4. PCQ envelope 빌드 (pcq_record.code에 생성 train.py vendoring + sha256) → POST {TC}/ingest
  5. state 갱신 (성공률/best_auroc/history), lineage(derives_from/exploration)
  6. 매 N round 알림

검증 대상: 코드 생성 성공률이 corpus와 함께 오르는가 (1차) + 코드 진화 + best AUROC.
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
# 설정
# ----------------------------------------------------------------------------

CQ_BIN = "/Users/changmin/.local/bin/cq"
PROJECT_ID = "2f285d78-927f-4ad6-9fe8-1159915780f4"  # cq_test
WORKER_ID = "37f67d0d-5c41-4e9d-b30b-7ae7ddd4f836"  # my-notebook
DATA_ROOT = "/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection"
CATEGORY = "bottle"
TC_URL = "http://127.0.0.1:8001"
JWT_PRIV = Path("/tmp/tc-dev/cq_priv.pem")
JWT_ISS, JWT_AUD, CONTRIB_ID = "cq.pilab.kr", "the-commons", "poc-codegen-bottle"
STATE_FILE = Path(__file__).parent.parent / ".cq" / "runtime" / "state" / "bottle_loop_state.json"
DEFAULT_INTENT = "MVTec bottle 이미지/픽셀 이상탐지 AUROC 최대화"

# cq 하네스 PATH에 uv 없음 → command 안에서 export (M0에서 확정)
CMD_PREFIX = 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH" && uv run --no-project'

METRIC_RE = re.compile(r"@([a-zA-Z_][a-zA-Z0-9_]*)=([-+0-9.eE]+)")


# ----------------------------------------------------------------------------
# cq mcp stdio JSON-RPC 클라이언트 (M0 레시피)
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
            "clientInfo": {"name": "bottle-loop", "version": "1"},
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

    # --- 디스패치 헬퍼 ---

    def dispatch(self, *, name: str, command: str, code: str, requirements: list[str]) -> str:
        """create_job → create_run → write_file → control_job(start). job_id 반환."""
        cj = self.call("create_job", {
            "project_id": PROJECT_ID, "name": name, "command": command,
            "config": json.dumps({"metrics": ["image_auroc", "pixel_auroc"], "requirements": requirements}),
        })
        m = re.search(r"([0-9a-f-]{36})", cj)
        if not m:
            raise RuntimeError(f"create_job 실패: {cj[:200]}")
        jid = m.group(1)
        self.call("create_run", {"job_id": jid, "worker_id": WORKER_ID})
        ws_dir = Path(f"/Users/changmin/.cq/workspace/{jid}")
        ws = str(ws_dir / "train.py")
        # cq write_file 시도 (NATS) → 로컬 직접 쓰기로 fallback (노트북=워커 로컬, NATS 우회)
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
        """워크스페이스 train_run.log 회수 (실패 traceback 환류용).

        wrapper가 노트북=워커 로컬이므로 cq read_file(NATS, 불안정) 대신 로컬
        파일시스템에서 직접 읽는다 — NATS RPC 우회.
        """
        p = Path(f"/Users/changmin/.cq/workspace/{job_id}/train_err.log")
        try:
            if p.exists():
                return p.read_text(errors="replace")[-tail_chars:]
        except Exception:  # noqa: BLE001
            pass
        return ""


# ----------------------------------------------------------------------------
# TC HTTP
# ----------------------------------------------------------------------------


def issue_jwt() -> str:
    now = int(time.time())
    payload = {"sub": CONTRIB_ID, "iss": JWT_ISS, "aud": JWT_AUD,
               "iat": now, "exp": now + 28800, "origin": "internal"}  # 8h
    return jwt.encode(payload, JWT_PRIV.read_bytes(), algorithm="RS256")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def call_codegen(client: httpx.Client, token: str, tc_url: str, data_dirs: list[str], intent: str) -> dict[str, Any]:
    r = client.post(f"{tc_url}/codegen", json={"data_dirs": data_dirs, "intent": intent},
                    headers=_headers(token), timeout=180.0)
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


def build_envelope(*, evidence_id: str, recipe_id: str, code: str, requirements: list[str],
                   metrics: dict[str, Any], sources: list[str], intent: str,
                   policy_meta: dict, lineage_type: str | None, lineage_target: str | None) -> dict[str, Any]:
    from the_commons.library.content_hash import compute_integrity

    code_sha = hashlib.sha256(code.encode()).hexdigest()
    attribution: dict[str, Any] = {"author": {"id": "codegen-loop", "kind": "agent"},
                                   "operator": CONTRIB_ID, "policy": policy_meta}
    if sources:
        attribution["sources"] = sources
    pcq: dict[str, Any] = {
        "intent": {"goal": "exploration", "description": intent,
                   "expected_baseline": {"metric": "image_auroc", "value": 0.9},
                   "tolerance": {"direction": "higher_is_better", "margin": 0.02}},
        "data_fingerprint": {"modality": "vision", "sample_count_band": "100-1k",
                             "schema_summary": {"dataset": "mvtec-bottle"}},
        "config": {"recipe_id": recipe_id},
        "metrics": metrics,
        "worker_spec": {"cpu_cores": 8, "ram_gb": 16, "gpu_model": "apple-mps", "vram_gb": 0, "has_gpu": False},
        "attribution": attribution,
        # PCQ code vendoring: 생성 train.py 전체 봉인 (재현/감사 단위)
        "code": {"content_sha256": code_sha, "content": code,
                 "scope": {"kind": "entry_script", "files": ["train.py"]},
                 "requirements": requirements},
        "seeds": {"main": 42, "data": "filesystem-order"},
        "data_ref": {"uri": f"file://{DATA_ROOT}/{CATEGORY}", "content_sha256": "mvtec-bottle-local",
                     "size_bytes": 157286400},
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
    best_auroc: float | None = None
    n_success: int = 0
    n_fail: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, p: Path) -> "LoopState":
        if not p.exists():
            return cls()
        d = json.loads(p.read_text())
        return cls(d.get("last_round", 0), d.get("last_evidence_id"), d.get("best_evidence_id"),
                   d.get("best_auroc"), d.get("n_success", 0), d.get("n_fail", 0), d.get("history", []))

    def save(self, p: Path) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "last_round": self.last_round, "last_evidence_id": self.last_evidence_id,
            "best_evidence_id": self.best_evidence_id, "best_auroc": self.best_auroc,
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
# 메인 루프
# ----------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--rounds", type=int, default=0, help="0이면 시간 기준")
    ap.add_argument("--notify-every", type=int, default=5)
    ap.add_argument("--run-timeout", type=int, default=1200)
    ap.add_argument("--tc-url", default=TC_URL)
    args = ap.parse_args()
    tc_url = args.tc_url

    state = LoopState.load(STATE_FILE)
    token = issue_jwt()
    # 데이터 구조를 2단계 깊이로 보여줌 (train/good, test/<defects> 등) — 코드가
    # 데이터 로딩 경로(train/good/*.png)를 정확히 잡게 해 num_samples=0 반복 감소.
    base = Path(DATA_ROOT) / CATEGORY
    data_dirs = []
    if base.is_dir():
        for sub in sorted(base.iterdir()):
            if sub.is_dir():
                children = [c.name for c in sorted(sub.iterdir()) if c.is_dir()]
                data_dirs.append(
                    f"{CATEGORY}/{sub.name}/ (하위: {children})" if children else f"{CATEGORY}/{sub.name}/"
                )
    else:
        data_dirs = [CATEGORY]
    deadline = time.time() + args.hours * 3600
    target_rounds = args.rounds if args.rounds > 0 else float("inf")

    print(f"🚀 bottle codegen loop | TC={tc_url} | resume round={state.last_round} | "
          f"deadline={args.hours}h | data_dirs={data_dirs}", flush=True)

    cq = CqMcpClient()
    with httpx.Client() as http:
        rnd = state.last_round
        while rnd < target_rounds and time.time() < deadline:
            rnd += 1
            print(f"\n— round {rnd} —", flush=True)
            # 1. 코드 생성 (TC 소믈리에)
            try:
                cg = call_codegen(http, token, tc_url, data_dirs, DEFAULT_INTENT)
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ /codegen 실패: {exc} — skip", flush=True)
                time.sleep(5); continue
            code = cg.get("generated_code")
            if not code:
                print("  ⚠ 생성 코드 없음 — skip", flush=True); continue
            recipe_id = cg.get("recipe_id", "mvtec-anomaly")
            reqs = cg.get("requirements", [])
            sources = cg.get("sources", [])
            print(f"  ← codegen: recipe={recipe_id} reqs={reqs} sources={len(sources)} code_len={len(code)} corpus={cg.get('corpus_size')}", flush=True)

            # 2. cq 디스패치
            with_flags = " ".join(f"--with {r}" for r in reqs if re.match(r"^[A-Za-z0-9_.\-]+$", r))
            # tee로 stdout(metric 파싱) 유지 + train_run.log(traceback 회수). pipefail로 실패 감지.
            # stdout(@image_auroc)은 cq metric writer로 직접, stderr(traceback)만 파일로.
            # tee/파이프는 cq metric 파싱을 막으므로 2>로 분리 (stdout 비파이프 유지).
            command = (
                f'{CMD_PREFIX} {with_flags} '
                f'python -u train.py --data-root {DATA_ROOT} 2> train_err.log'
            )
            try:
                jid = cq.dispatch(name=f"bottle-r{rnd:04d}", command=command, code=code, requirements=reqs)
                status = cq.poll(jid, run_timeout=args.run_timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ cq 디스패치 실패: {exc} — skip", flush=True)
                time.sleep(5); continue
            metrics, ok = parse_metrics(status)
            # 실패 시 train_run.log tail을 traceback으로 회수 → 다음 생성 환류
            if not ok:
                log_tail = cq.read_run_log(jid)
                if log_tail:
                    metrics["stderr_tail"] = log_tail
            print(f"  ← run: ok={ok} metrics_keys={list(metrics.keys())}", flush=True)

            # 3. envelope (코드 vendoring) + ingest
            eid = f"ev-bottle-{rnd:04d}-{uuid.uuid4().hex[:6]}"
            if state.last_evidence_id:
                lt, ltarget = "derives_from", state.last_evidence_id
            else:
                lt, ltarget = None, None
            policy_meta = {"branch": "codegen", "round_id": f"r{rnd}", "recipe_id": recipe_id}
            env = build_envelope(evidence_id=eid, recipe_id=recipe_id, code=code, requirements=reqs,
                                 metrics=metrics, sources=sources, intent=DEFAULT_INTENT,
                                 policy_meta=policy_meta, lineage_type=lt, lineage_target=ltarget)
            if not call_ingest(http, token, tc_url, env):
                print("  ↷ ingest 실패 → state 갱신 없이 다음", flush=True); continue
            print(f"  → ingest: {eid}", flush=True)

            # 4. state
            auroc = metrics.get("image_auroc")
            if ok:
                state.n_success += 1
            else:
                state.n_fail += 1
            if ok and isinstance(auroc, (int, float)) and (state.best_auroc is None or auroc > state.best_auroc):
                state.best_auroc = float(auroc); state.best_evidence_id = eid
                print(f"  ★ new best image_auroc={auroc}", flush=True)
            state.last_round = rnd; state.last_evidence_id = eid
            total = state.n_success + state.n_fail
            state.history.append({"round": rnd, "evidence_id": eid, "recipe_id": recipe_id,
                                 "ok": ok, "metrics": metrics, "ts": datetime.now(timezone.utc).isoformat()})
            state.save(STATE_FILE)

            if rnd % args.notify_every == 0:
                rate = state.n_success / total if total else 0
                print(f"\n{'='*60}\n📊 round={rnd} 성공률={rate:.0%} ({state.n_success}/{total}) "
                      f"best_auroc={state.best_auroc}\n{'='*60}", flush=True)

    cq.close()
    print("\n✓ loop finished.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
