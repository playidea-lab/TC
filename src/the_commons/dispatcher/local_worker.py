"""LocalWorker — 현 cq_dispatch.py의 동작을 Worker Protocol로 흡수.

워커 == 노트북(같은 파일 시스템) 전제. mvtec(Mac/MPS) 환경에서 검증된 경로.
원격 GPU는 CqRemoteWorker(D3)가 담당.

reuse: cq_dispatch.CqMcpClient(NATS stdio JSON-RPC), parse_metrics(stdout 파싱).
구 cq_dispatch.py는 D7에서 이 LocalWorker로 격하 예정 — 그때까지는 import로 공존.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# 구 cq_dispatch에서 검증된 헬퍼 재사용. D7에서 이쪽으로 옮길 예정.
from .cq_client import CqMcpClient, parse_metrics

from .types import JobSpec
from .worker import Worker

_JOB_ID_RE = re.compile(r"([0-9a-f-]{36})")


class LocalWorker(Worker):
    """워커 = 로컬 노트북. 파일 시스템 직접 접근, cq NATS는 RPC 용도."""

    def __init__(self, project_id: str, worker_id: str,
                 workspace_root: Path | str | None = None) -> None:
        if not project_id or not worker_id:
            raise ValueError("project_id·worker_id 필요(env CQ_PROJECT_ID/CQ_WORKER_ID 또는 인자)")
        self._project_id = project_id
        self._worker_id = worker_id
        self._workspace_root = Path(workspace_root) if workspace_root else Path(
            os.environ.get("CQ_WORKSPACE_ROOT", str(Path.home() / ".cq" / "workspace")))
        self._cq: CqMcpClient | None = None      # lazy — 테스트서 모킹 가능

    def _client(self) -> CqMcpClient:
        if self._cq is None:
            self._cq = CqMcpClient()
        return self._cq

    def submit(self, spec: JobSpec) -> str:
        if not spec.command:
            raise ValueError("spec.command 비어있음 — caller가 command 채워야(profile 결정)")
        cq = self._client()
        cj = cq.call("create_job", {
            "project_id": self._project_id,
            "name": spec.name,
            "command": spec.command,
            "config": json.dumps({"metrics": spec.metric_keys, "requirements": spec.requirements}),
        })
        m = _JOB_ID_RE.search(cj)
        if not m:
            raise RuntimeError(f"create_job 실패: {cj[:200]}")
        jid = m.group(1)
        cq.call("create_run", {"job_id": jid, "worker_id": self._worker_id})

        # 워크스페이스에 코드+aux+config 기록 (워커=로컬 파일시스템 가정).
        ws_dir = self._workspace_root / jid
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "train.py").write_text(spec.code, encoding="utf-8")
        for name, content in spec.aux_files.items():
            (ws_dir / name).write_text(content, encoding="utf-8")
        # cq_config.json: pcq.config()가 읽음. autoresearch 같은 비-pcq는 spec.config={}.
        (ws_dir / "cq_config.json").write_text(json.dumps(spec.config), encoding="utf-8")

        # NATS write_file은 best-effort(원격 워커였다면 정본 — 로컬은 위 파일시스템이 정본).
        cq.call("write_file", {"worker_id": self._worker_id,
                                "path": str(ws_dir / "train.py"), "content": spec.code})
        cq.call("control_job", {"action": "start", "job_id": jid,
                                 "worker_id": self._worker_id})
        return jid

    def poll(self, job_id: str, timeout: int) -> tuple[bool, dict, str]:
        cq = self._client()
        status_text = cq.poll(job_id, run_timeout=timeout)
        metrics, ok = parse_metrics(status_text)
        return ok, metrics, status_text

    def download(self, job_id: str, path: str) -> str | None:
        p = self._workspace_root / job_id / path
        if not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def tail_stderr(self, job_id: str, n_lines: int = 50) -> str:
        # train_err.log는 보통 작아서(<100KB) 전체 읽고 line 단위 tail. 큰 경우엔 추후 최적화.
        p = self._workspace_root / job_id / "train_err.log"
        if not p.exists():
            return ""
        try:
            lines = p.read_text(errors="replace").splitlines()
            return "\n".join(lines[-n_lines:])
        except OSError:
            return ""

    def close(self) -> None:
        if self._cq is not None:
            self._cq.close()
            self._cq = None
