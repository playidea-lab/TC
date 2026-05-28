"""CqRemoteWorker — 원격 cq 워커(4090/3090 등 GPU 머신)용 Worker 구현.

LocalWorker는 워커 == 노트북(공유 파일 시스템) 전제라 원격 워커서 만든 describe.json /
train_err.log를 못 읽는다. CqRemoteWorker는 cq MCP `write_file` (NATS, 원격 워커
workspace/{job_id}/에 파일 작성) + `read_file` (역방향 회수)으로 파일 입출력을
*모두 NATS 위*에 올린다.

R1 Phase D2. autoresearch nanochat(원격 GPU) 디스패치의 본격 진입로.
GPU 워커 온라인(S1~S3) 후 smoke로 인터페이스 검증.
"""

from __future__ import annotations

import json
import re

from .cq_client import CqMcpClient, parse_metrics
from .types import JobSpec
from .worker import Worker

_JOB_ID_RE = re.compile(r"([0-9a-f-]{36})")


class CqRemoteWorker(Worker):
    """원격 워커. 모든 파일 I/O는 cq NATS(write_file/read_file)로."""

    def __init__(self, project_id: str, worker_id: str) -> None:
        if not project_id or not worker_id:
            raise ValueError("project_id·worker_id 필요")
        self._project_id = project_id
        self._worker_id = worker_id
        self._cq: CqMcpClient | None = None        # lazy, 테스트 모킹 가능

    def _client(self) -> CqMcpClient:
        if self._cq is None:
            self._cq = CqMcpClient()
        return self._cq

    def submit(self, spec: JobSpec) -> str:
        if not spec.command:
            raise ValueError("spec.command 비어있음 — caller가 채워야(profile build_command)")
        cq = self._client()
        cj = cq.call("create_job", {
            "project_id": self._project_id,
            "name": spec.name,
            "command": spec.command,
            "config": json.dumps({
                "metrics": spec.metric_keys, "requirements": spec.requirements,
            }),
        })
        m = _JOB_ID_RE.search(cj)
        if not m:
            raise RuntimeError(f"create_job 실패: {cj[:200]}")
        jid = m.group(1)
        cq.call("create_run", {"job_id": jid, "worker_id": self._worker_id})

        # 원격 워커 workspace/{jid}/ 에 코드·aux·config 작성. LocalWorker와 달리 *로컬 파일
        # 시스템 직접 쓰기 안 함* — 원격은 NATS write_file이 정본.
        cq.call("write_file", {
            "worker_id": self._worker_id, "job_id": jid,
            "path": "train.py", "content": spec.code,
        })
        cq.call("write_file", {
            "worker_id": self._worker_id, "job_id": jid,
            "path": "cq_config.json", "content": json.dumps(spec.config),
        })
        for name, content in spec.aux_files.items():
            cq.call("write_file", {
                "worker_id": self._worker_id, "job_id": jid,
                "path": name, "content": content,
            })
        cq.call("control_job", {"action": "start", "job_id": jid, "worker_id": self._worker_id})
        return jid

    def poll(self, job_id: str, timeout: int) -> tuple[bool, dict, str]:
        cq = self._client()
        status_text = cq.poll(job_id, run_timeout=timeout)
        metrics, ok = parse_metrics(status_text)
        return ok, metrics, status_text

    def download(self, job_id: str, path: str) -> str | None:
        """원격 워커 workspace/{job_id}/<path> 회수. 없거나 실패면 None.

        cq read_file은 텍스트 반환(파일 없으면 에러 메시지). 휴리스틱: 응답이 짧고
        에러 패턴이면 None, 아니면 content. cq 측이 명시적 not_found 신호를 주면
        그걸로 갈음(현재는 휴리스틱).
        """
        cq = self._client()
        try:
            r = cq.call("read_file", {
                "worker_id": self._worker_id, "job_id": job_id, "path": path,
            })
        except Exception:
            return None
        if not r or _looks_like_error(r):
            return None
        return r

    def tail_stderr(self, job_id: str, n_lines: int = 50) -> str:
        """train_err.log를 NATS read_file로 회수, 마지막 N줄. ★V5/V11 자기수정 입력."""
        content = self.download(job_id, "train_err.log")
        if not content:
            return ""
        return "\n".join(content.splitlines()[-n_lines:])

    def close(self) -> None:
        if self._cq is not None:
            self._cq.close()
            self._cq = None


def _looks_like_error(text: str) -> bool:
    """cq read_file이 not-found/permission 등 에러를 텍스트로 반환할 때 휴리스틱 판별."""
    if len(text) < 200 and any(p in text.lower() for p in (
        "not found", "no such file", "error:", "failed", "permission denied",
    )):
        return True
    return False


__all__ = ["CqRemoteWorker"]
