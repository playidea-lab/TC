"""cq-tc-autonomous-experiment-loop v1 — 폐루프 wrapper (cq 우회 임시 host).

idea: `.cq/runtime/ideas/cq-tc-autonomous-experiment-loop.md`

폐루프 흐름 (매 round):
  1. intent 파일 읽기 (사람이 steer 가능)
  2. POST /recommend (intent + worker_spec + round_id) → next_config + policy
  3. cold_start면 휴리스틱 recipe로 default config, 아니면 next_config 그대로
  4. train.py subprocess 실행, stdout @key=value 메트릭 파싱
  5. PCQ envelope build (attribution.policy + lineage type 마커)
  6. POST /ingest → 도서관 적재
  7. state 갱신 (last_round, last_evidence_id, best_metric), 저장
  8. 매 N round마다 stdout 알림

cq 워커 인프라가 풀리면 train.py subprocess 자리를 cq 디스패치로 교체.
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

from the_commons.library.content_hash import compute_integrity

# ----------------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRAIN_SCRIPT = REPO_ROOT / "scripts" / "train_mnist.py"
DEFAULT_STATE_FILE = REPO_ROOT / ".cq" / "runtime" / "state" / "loop_state.json"
DEFAULT_INTENT_FILE = REPO_ROOT / ".cq" / "runtime" / "state" / "loop_intent.txt"
DEFAULT_JWT_PRIV = Path("/tmp/tc-dev/cq_priv.pem")
DEFAULT_TC_URL = "http://127.0.0.1:8000"
DEFAULT_INTENT = "MNIST test_acc 더 올리기"
CONTRIB_ID = "poc-cq-mnist-loop"
JWT_ISS = "cq.pilab.kr"
JWT_AUD = "the-commons"

# 메트릭 파싱: `@key=value` 라인에서 key=value 추출. 마지막 등장 값을 채택.
METRIC_LINE_RE = re.compile(r"@([a-zA-Z_][a-zA-Z0-9_]*)=([^\s]+)")


# ----------------------------------------------------------------------------
# 영속 상태
# ----------------------------------------------------------------------------


@dataclass
class LoopState:
    """영속 state. round 사이 재시작에 이어받을 정보."""

    last_round: int = 0
    last_evidence_id: str | None = None
    best_evidence_id: str | None = None
    best_metric_value: float | None = None
    best_metric_name: str | None = None
    current_intent: str = DEFAULT_INTENT
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_round": self.last_round,
            "last_evidence_id": self.last_evidence_id,
            "best_evidence_id": self.best_evidence_id,
            "best_metric_value": self.best_metric_value,
            "best_metric_name": self.best_metric_name,
            "current_intent": self.current_intent,
            "history": self.history[-50:],  # 마지막 50개만 보존 — 파일 크기 cap
        }

    @classmethod
    def load(cls, path: Path) -> "LoopState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            last_round=data.get("last_round", 0),
            last_evidence_id=data.get("last_evidence_id"),
            best_evidence_id=data.get("best_evidence_id"),
            best_metric_value=data.get("best_metric_value"),
            best_metric_name=data.get("best_metric_name"),
            current_intent=data.get("current_intent", DEFAULT_INTENT),
            history=data.get("history", []),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def load_intent(path: Path, fallback: str) -> str:
    """intent 파일이 있으면 첫 줄을 읽고, 없으면 fallback 유지."""
    if not path.exists():
        return fallback
    text = path.read_text(encoding="utf-8").strip()
    return text or fallback


# ----------------------------------------------------------------------------
# JWT
# ----------------------------------------------------------------------------


def issue_dev_jwt(priv_path: Path) -> str:
    now = int(time.time())
    payload = {
        "sub": CONTRIB_ID,
        "iss": JWT_ISS,
        "aud": JWT_AUD,
        "iat": now,
        "exp": now + 3600,
        "origin": "internal",
    }
    return jwt.encode(payload, priv_path.read_bytes(), algorithm="RS256")


# ----------------------------------------------------------------------------
# train subprocess + 메트릭 파싱
# ----------------------------------------------------------------------------


def run_training(
    train_script: Path, next_config: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """train.py를 subprocess로 실행. (metrics_dict, success) 반환.

    next_config의 lr/batch_size/epochs/seed를 CLI args로 전달. 그 외 key는 무시
    (v1: train_mnist.py가 받는 인자가 고정). stdout에서 @key=value 라인 누적 → 메트릭.
    실패 시 metrics에 failed:true 마커 + exit_code.
    """
    # --with torch/torchvision: 로컬 host(노트북)에서 TheCommons venv엔 torch가 없으므로
    # uv ad-hoc 격리 환경에 주입. cq 워커로 교체되면 이 cmd 전체가 cq 디스패치로 대체된다.
    cmd = [
        "uv",
        "run",
        "--with",
        "torch",
        "--with",
        "torchvision",
        "python",
        "-u",
        str(train_script),
        "--lr",
        str(next_config.get("lr", 0.01)),
        "--batch_size",
        str(next_config.get("batch_size", 128)),
        "--epochs",
        str(next_config.get("epochs", 1)),
        "--seed",
        str(next_config.get("seed", 42)),
    ]
    print(f"  ▶ subprocess: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(  # noqa: S603 — trusted cmd
        cmd, capture_output=True, text=True, cwd=REPO_ROOT
    )
    metrics: dict[str, Any] = {}
    for match in METRIC_LINE_RE.finditer(proc.stdout):
        key, raw = match.group(1), match.group(2)
        try:
            value: Any = float(raw)
            if value.is_integer() and "." not in raw:
                value = int(value)
        except ValueError:
            value = raw
        metrics[key] = value
    success = proc.returncode == 0 and bool(metrics)
    if not success:
        metrics["failed"] = True
        metrics["exit_code"] = proc.returncode
        # stderr 일부만 — envelope 크기 cap
        if proc.stderr:
            metrics["stderr_tail"] = proc.stderr[-500:]
    return metrics, success


# ----------------------------------------------------------------------------
# envelope 빌더
# ----------------------------------------------------------------------------


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_envelope(
    *,
    evidence_id: str,
    recipe_id: str,
    next_config: dict[str, Any],
    metrics: dict[str, Any],
    code_sha: str,
    seed: int,
    intent_goal: str,
    policy_meta: dict[str, Any] | None,
    lineage_type: str | None,
    lineage_target: str | None,
) -> dict[str, Any]:
    """PCQ 2.x envelope 빌드 — attribution.policy + 분기별 lineage type 박음."""
    attribution: dict[str, Any] = {
        "author": {"id": "loop-runner", "kind": "agent"},
        "operator": CONTRIB_ID,
    }
    if policy_meta is not None:
        attribution["policy"] = policy_meta

    # PCQ Intent.goal은 enum 5개 (exploration/hyperparam_sweep/...). 사용자가 intent_file에
    # 자유 텍스트로 박은 steering 메시지는 Intent.extra("description") 필드로 보존한다.
    pcq_record: dict[str, Any] = {
        "intent": {
            "goal": "exploration",
            "description": intent_goal,
            "expected_baseline": {"metric": "test_acc", "value": 0.95},
            "tolerance": {"direction": "higher_is_better", "margin": 0.02},
        },
        "data_fingerprint": {
            "modality": "vision",
            "sample_count_band": "10k-100k",
            "schema_summary": {"shape": "1x28x28", "classes": 10},
        },
        "config": {
            "recipe_id": recipe_id,
            **next_config,
        },
        "metrics": metrics,
        "worker_spec": {
            "cpu_cores": 8,
            "ram_gb": 16,
            "gpu_model": "host-cpu",
            "vram_gb": 0,
            "has_gpu": False,
        },
        "attribution": attribution,
        "code": {
            "content_sha256": code_sha,
            "scope": {
                "kind": "entry_script",
                "files": ["scripts/train_mnist.py"],
            },
        },
        "seeds": {"main": seed, "data": "torch-default"},
        "data_ref": {
            "uri": "torchvision://datasets/MNIST",
            "content_sha256": "mnist-canonical-mirror",
            "size_bytes": 11594722,
        },
        "contract_version": "2.0",
    }
    integrity = compute_integrity(pcq_record)
    pcq_record["integrity"] = integrity

    envelope: dict[str, Any] = {
        "evidence_id": evidence_id,
        "tier": "real",
        "outreach_origin": "internal",
        "synthetic_source": None,
        "pcq_record": pcq_record,
    }
    if lineage_type and lineage_target:
        lineage_meta: dict[str, Any] = {}
        if policy_meta is not None:
            lineage_meta = {
                "branch": policy_meta.get("branch"),
                "epsilon": policy_meta.get("epsilon"),
                "policy_version": policy_meta.get("version"),
                "wild_card_fired": policy_meta.get("wild_card_fired"),
            }
        envelope["lineage"] = [
            {
                "type": lineage_type,
                "target_evidence_id": lineage_target,
                "metadata": lineage_meta or None,
            }
        ]
    return envelope


# ----------------------------------------------------------------------------
# HTTP 호출 헬퍼
# ----------------------------------------------------------------------------


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def call_recommend(
    client: httpx.Client, token: str, tc_url: str, query: dict[str, Any], round_id: str
) -> dict[str, Any]:
    r = client.post(
        f"{tc_url}/recommend",
        json={"query": query, "round_id": round_id},
        headers=_auth_headers(token),
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def call_ingest(
    client: httpx.Client, token: str, tc_url: str, envelope: dict[str, Any]
) -> dict[str, Any]:
    r = client.post(
        f"{tc_url}/ingest",
        json={"evidence": envelope},
        headers=_auth_headers(token),
        timeout=30.0,
    )
    if r.status_code >= 400:
        print(f"  ⚠ /ingest {envelope['evidence_id']} → {r.status_code}: {r.text[:300]}", flush=True)
    r.raise_for_status()
    return r.json()


# ----------------------------------------------------------------------------
# 알림
# ----------------------------------------------------------------------------


def emit_notification(state: LoopState, last_metrics: dict[str, Any]) -> None:
    """매 N round마다 stdout 알림 — 사람이 들여다보는 hook."""
    print("\n" + "=" * 70, flush=True)
    print(f"📊 NOTIFY @ round={state.last_round}  ({datetime.now(timezone.utc).isoformat()})", flush=True)
    print(f"   current_intent: {state.current_intent}", flush=True)
    print(
        f"   best: id={state.best_evidence_id}  "
        f"{state.best_metric_name}={state.best_metric_value}",
        flush=True,
    )
    print(f"   last_metrics: {last_metrics}", flush=True)
    recent = state.history[-5:]
    print(f"   recent {len(recent)} rounds:", flush=True)
    for entry in recent:
        print(
            f"     - round={entry['round']} branch={entry.get('branch')} "
            f"recipe={entry.get('recipe_id')} metrics={entry.get('metrics')}",
            flush=True,
        )
    print("=" * 70 + "\n", flush=True)


# ----------------------------------------------------------------------------
# 메인 루프
# ----------------------------------------------------------------------------


def primary_metric(metrics: dict[str, Any]) -> tuple[str | None, float | None]:
    """metrics에서 첫 numeric 값을 best 비교용으로 추출. test_acc 우선."""
    for preferred in ("test_acc", "val_acc", "accuracy", "auc"):
        v = metrics.get(preferred)
        if isinstance(v, int | float):
            return preferred, float(v)
    for k, v in metrics.items():
        if isinstance(v, int | float):
            return k, float(v)
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="cq-tc-autonomous-experiment-loop v1")
    parser.add_argument("--rounds", type=int, default=0, help="0이면 무제한")
    parser.add_argument("--notify-every", type=int, default=10)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--intent-file", type=Path, default=DEFAULT_INTENT_FILE)
    parser.add_argument("--tc-url", type=str, default=DEFAULT_TC_URL)
    parser.add_argument("--jwt-priv", type=Path, default=DEFAULT_JWT_PRIV)
    parser.add_argument("--train-script", type=Path, default=DEFAULT_TRAIN_SCRIPT)
    parser.add_argument("--sleep-between", type=float, default=0.0, help="round 간 sleep (sec)")
    args = parser.parse_args()

    state = LoopState.load(args.state_file)
    code_sha = _sha256_file(args.train_script)
    token = issue_dev_jwt(args.jwt_priv)

    print(f"🚀 loop start | state={args.state_file} | code_sha={code_sha[:16]}…", flush=True)
    print(f"   resume from round={state.last_round}, last_evidence={state.last_evidence_id}", flush=True)

    target_rounds = args.rounds if args.rounds > 0 else float("inf")

    with httpx.Client() as client:
        round_no = state.last_round
        while round_no < target_rounds:
            round_no += 1
            round_id = f"r-{round_no:06d}-{uuid.uuid4().hex[:6]}"
            intent_goal = load_intent(args.intent_file, state.current_intent)
            state.current_intent = intent_goal

            print(f"\n— round {round_no} | round_id={round_id} | intent='{intent_goal}'", flush=True)

            # 1. recommend
            query = {
                "intent": {
                    "goal": "exploration",
                    "description": intent_goal,
                    "expected_baseline": {"metric": "test_acc", "value": 0.95},
                    "tolerance": {"direction": "higher_is_better", "margin": 0.02},
                },
                "data_fingerprint": {
                    "modality": "vision",
                    "sample_count_band": "10k-100k",
                    "schema_summary": {"shape": "1x28x28", "classes": 10},
                },
                "worker_spec": {
                    "cpu_cores": 8,
                    "ram_gb": 16,
                    "gpu_model": "host-cpu",
                    "vram_gb": 0,
                    "has_gpu": False,
                },
            }
            rec = call_recommend(client, token, args.tc_url, query, round_id)
            cands = rec.get("candidates", [])
            if not cands:
                print("  ⚠ /recommend returned no candidates — skip round", flush=True)
                continue
            top = cands[0]
            recipe_id = top["recipe_id"]
            policy_meta = top.get("policy")
            next_config = top.get("next_config") or {
                "lr": 0.01,
                "batch_size": 128,
                "epochs": 1,
                "seed": 42,
            }
            branch = (policy_meta or {}).get("branch", "cold_start")
            print(f"  ← recommend: recipe={recipe_id} branch={branch} next_config={next_config}", flush=True)

            # 2. train
            metrics, ok = run_training(args.train_script, next_config)
            print(f"  ← train: ok={ok} metrics={metrics}", flush=True)

            # 3. envelope build (분기별 lineage 타입)
            evidence_id = f"ev-loop-{round_no:06d}-{uuid.uuid4().hex[:6]}"
            if branch == "explore":
                lineage_type: str | None = "exploration"
                lineage_target = state.best_evidence_id or state.last_evidence_id
            elif state.last_evidence_id:
                lineage_type = "derives_from"
                lineage_target = state.last_evidence_id
            else:
                lineage_type = None
                lineage_target = None

            envelope = build_envelope(
                evidence_id=evidence_id,
                recipe_id=recipe_id,
                next_config=next_config,
                metrics=metrics,
                code_sha=code_sha,
                seed=int(next_config.get("seed", 42)),
                intent_goal=intent_goal,
                policy_meta=policy_meta,
                lineage_type=lineage_type,
                lineage_target=lineage_target,
            )

            # 4. ingest
            call_ingest(client, token, args.tc_url, envelope)
            print(f"  → ingest: {evidence_id}", flush=True)

            # 5. state 갱신
            metric_name, metric_val = primary_metric(metrics)
            if (
                metric_val is not None
                and not metrics.get("failed")
                and (
                    state.best_metric_value is None
                    or metric_val > state.best_metric_value
                )
            ):
                state.best_metric_value = metric_val
                state.best_metric_name = metric_name
                state.best_evidence_id = evidence_id
                print(f"  ★ new best: {metric_name}={metric_val} ({evidence_id})", flush=True)

            state.last_round = round_no
            state.last_evidence_id = evidence_id
            state.history.append(
                {
                    "round": round_no,
                    "evidence_id": evidence_id,
                    "recipe_id": recipe_id,
                    "branch": branch,
                    "next_config": next_config,
                    "metrics": metrics,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            state.save(args.state_file)

            # 6. 알림
            if round_no % args.notify_every == 0:
                emit_notification(state, metrics)

            if args.sleep_between > 0:
                time.sleep(args.sleep_between)

    print("\n✓ loop finished.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
