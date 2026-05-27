"""cq–pcq–tc 한 사이클 PoC.

흐름:
  1. POST /recommend (cold-start)  — corpus 미적재 상태의 소믈리에 응답
  2. MNIST lr-sweep 3 run 시뮬레이션 — 학습 entry script(train_mnist.py)는 진짜
     (sha256 source). 메트릭은 결정적 함수로 생성 (PoC; cq 워커 통합은 다음 사이클).
  3. 각 run → PCQ 2.x envelope 빌드 (integrity.content_hash 진짜 계산)
  4. POST /ingest x 3 (도서관 적재, lineage edge 포함: 두번째부터 derives_from)
  5. POST /recommend (사이클 폐쇄)  — 방금 적재된 evidence가 hit로 등장하는지

사용:
  uv run python -m the_commons.db.migrate
  uv run uvicorn the_commons.main:app --port 8000 &
  uv run python scripts/cq_pcq_tc_oneshot.py
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

from the_commons.library.content_hash import compute_integrity

# ----------------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------------

TC_URL = "http://127.0.0.1:8000"
JWT_PRIV_PATH = Path("/tmp/tc-dev/cq_priv.pem")
JWT_ISS = "cq.pilab.kr"
JWT_AUD = "the-commons"
CONTRIB_ID = "poc-cq-mnist"

TRAIN_SCRIPT = Path(__file__).parent / "train_mnist.py"
RUN_ID_PREFIX = "ev-mnist-lr"
# 5개로 확장 — settings.recommend_top_n=5 이므로 sparse 게이트(hits<top_n)를
# 넘어가야 retrieve 경로가 cold-start가 아닌 진짜 추천 분기로 들어간다.
LR_SWEEP = [1e-4, 1e-3, 1e-2, 1e-1, 5e-1]


# ----------------------------------------------------------------------------
# JWT 발행
# ----------------------------------------------------------------------------


def issue_dev_jwt() -> str:
    """dev RSA 개인키로 RS256 JWT 발행."""
    now = int(time.time())
    payload = {
        "sub": CONTRIB_ID,
        "iss": JWT_ISS,
        "aud": JWT_AUD,
        "iat": now,
        "exp": now + 3600,
        "origin": "internal",
    }
    priv = JWT_PRIV_PATH.read_bytes()
    return jwt.encode(payload, priv, algorithm="RS256")


# ----------------------------------------------------------------------------
# MNIST run 시뮬레이션
# ----------------------------------------------------------------------------


def simulate_mnist_run(lr: float, seed: int = 42) -> dict[str, float]:
    """결정적 합성 metrics — lr별 1-epoch MNIST 성능 곡선 근사.

    lr=1e-3 → 미흡(0.88), 1e-2 → 좋음(0.97), 1e-1 → 발산(0.45) 처럼.
    실제 학습 대체용 (PoC; train_mnist.py 코드 자체는 진짜).
    """
    # 단순 ridge: lr 로그축 기준 peak 1e-2.
    log_lr = math.log10(lr)
    # peak at log_lr = -2 (lr=1e-2), 양옆 가우시안 감쇠
    sigma = 0.7
    peak = 0.97
    floor = 0.10
    acc = floor + (peak - floor) * math.exp(-((log_lr + 2.0) ** 2) / (2 * sigma**2))
    train_loss = max(0.05, 2.3 * (1 - acc))  # CE loss 대략 변환
    return {
        "test_acc": round(acc, 4),
        "train_loss": round(train_loss, 4),
        "epochs": 1,
        "seed": seed,
    }


# ----------------------------------------------------------------------------
# PCQ envelope 빌더
# ----------------------------------------------------------------------------


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_envelope(
    *,
    evidence_id: str,
    lr: float,
    metrics: dict[str, Any],
    code_sha: str,
    seed: int,
    lineage_parent: str | None = None,
) -> dict[str, Any]:
    """PCQ 2.x envelope 빌드 — integrity.content_hash 진짜 계산."""

    pcq_record: dict[str, Any] = {
        "intent": {
            "goal": "hyperparam_sweep",
            "expected_baseline": {"metric": "test_acc", "value": 0.95},
            "tolerance": {"direction": "higher_is_better", "margin": 0.02},
        },
        "data_fingerprint": {
            "modality": "vision",
            "sample_count_band": "10k-100k",
            "schema_summary": {"shape": "1x28x28", "classes": 10},
        },
        "config": {
            "recipe_id": "mnist-tinymlp",
            "lr": lr,
            "batch_size": 128,
            "epochs": 1,
            "optimizer": "sgd",
            "momentum": 0.9,
        },
        "metrics": metrics,
        "worker_spec": {
            "cpu_cores": 8,
            "ram_gb": 16,
            "gpu_model": "RTX3090",
            "vram_gb": 24,
            "has_gpu": True,
        },
        "attribution": {
            "author": {"id": "poc-author", "kind": "agent"},
            "operator": CONTRIB_ID,
        },
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

    # integrity 진짜 계산 (default allowlist)
    integrity = compute_integrity(pcq_record)
    pcq_record["integrity"] = integrity

    envelope: dict[str, Any] = {
        "evidence_id": evidence_id,
        "tier": "real",
        "outreach_origin": "internal",
        "synthetic_source": None,
        "pcq_record": pcq_record,
    }
    if lineage_parent:
        envelope["lineage"] = [
            {"type": "derives_from", "target_evidence_id": lineage_parent}
        ]
    return envelope


# ----------------------------------------------------------------------------
# 호출 헬퍼
# ----------------------------------------------------------------------------


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def call_recommend(client: httpx.Client, token: str, label: str) -> dict[str, Any]:
    body = {
        "query": {
            "intent": {
                "goal": "hyperparam_sweep",
                "expected_baseline": {"metric": "test_acc", "value": 0.95},
            },
            "data_fingerprint": {
                "modality": "vision",
                "sample_count_band": "10k-100k",
            },
            "worker_spec": {
                "cpu_cores": 8,
                "ram_gb": 16,
                "gpu_model": "RTX3090",
                "vram_gb": 24,
                "has_gpu": True,
            },
        }
    }
    r = client.post(f"{TC_URL}/recommend", json=body, headers=_auth_headers(token), timeout=60.0)
    print(f"\n=== /recommend [{label}] → {r.status_code} ===")
    try:
        data = r.json()
    except Exception:
        print(r.text)
        r.raise_for_status()
        return {}
    print(json.dumps(data, indent=2, ensure_ascii=False)[:1500])
    r.raise_for_status()
    return data


def call_ingest(
    client: httpx.Client, token: str, envelope: dict[str, Any]
) -> dict[str, Any]:
    r = client.post(
        f"{TC_URL}/ingest",
        json={"evidence": envelope},
        headers=_auth_headers(token),
        timeout=30.0,
    )
    print(f"  /ingest {envelope['evidence_id']} → {r.status_code}")
    if r.status_code >= 400:
        print("  body:", r.text[:400])
    r.raise_for_status()
    return r.json()


def call_evidence_get(
    client: httpx.Client, token: str, evidence_id: str
) -> dict[str, Any]:
    """L1 immutable record 재현 — content_hash·lineage 확인."""
    r = client.get(
        f"{TC_URL}/evidence/{evidence_id}",
        headers=_auth_headers(token),
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()


# ----------------------------------------------------------------------------
# 메인 흐름
# ----------------------------------------------------------------------------


def main() -> int:
    token = issue_dev_jwt()
    code_sha = _sha256_file(TRAIN_SCRIPT)
    print(f"train_mnist.py sha256={code_sha[:16]}…")

    with httpx.Client() as client:
        # Step A — cold-start recommend
        call_recommend(client, token, label="cold-start (before ingest)")

        # Step B+C+D — sweep runs → envelope → ingest
        evidence_ids: list[str] = []
        parent: str | None = None
        for i, lr in enumerate(LR_SWEEP):
            evidence_id = f"{RUN_ID_PREFIX}-{i:02d}-{uuid.uuid4().hex[:6]}"
            metrics = simulate_mnist_run(lr)
            print(f"\n[run {i}] lr={lr:.1e} → metrics={metrics}")
            env = build_envelope(
                evidence_id=evidence_id,
                lr=lr,
                metrics=metrics,
                code_sha=code_sha,
                seed=42 + i,
                lineage_parent=parent,
            )
            call_ingest(client, token, env)
            evidence_ids.append(evidence_id)
            parent = evidence_id

        # Step E — L1 immutable round-trip 검증 (도서관에 진짜 들어갔는가)
        print("\n=== L1 round-trip 검증 ===")
        for eid in evidence_ids:
            got = call_evidence_get(client, token, eid)
            ev = got["evidence"]
            pcq = ev["pcq_record"]
            lineage = ev.get("lineage") or []
            print(
                f"  {eid}  lr={pcq['config']['lr']:.1e}  acc={pcq['metrics']['test_acc']:.4f}  "
                f"content_hash={pcq['integrity']['content_hash'][:30]}…  "
                f"lineage={len(lineage)} edge(s)"
            )

        # Step F — closing recommend (사이클 폐쇄: 방금 evidence들이 hit로 보여야 함)
        rec = call_recommend(client, token, label="post-ingest (cycle closed)")
        ctx = rec.get("corpus_context", {})
        print(
            f"\ncorpus_context: real={ctx.get('real_count')} synthetic={ctx.get('synthetic_count')}"
        )
        print(f"candidates: {len(rec.get('candidates', []))}")

    print("\nOK — cq–pcq–tc 한 사이클 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
