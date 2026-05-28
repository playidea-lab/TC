"""Worker Protocol — 워커 토폴로지 추상화.

LocalWorker(현 cq_dispatch.py 동작 흡수, mvtec/MPS)와 CqRemoteWorker(원격 GPU + cq download
파일 회수)가 같은 Protocol을 충족한다. dispatcher_v2.dispatch는 워커 종류를 모른다.

submit이 upload+start를 합친 이유: cq의 흐름이 create_job → create_run → write file → start로
묶여 있어 파일 업로드 시점에 이미 job 컨텍스트가 필요. 분리하면 어색하다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import JobSpec


@runtime_checkable
class Worker(Protocol):
    """워커 인터페이스 — 모든 워커 구현은 5개 메서드(+close)를 제공한다."""

    def submit(self, spec: JobSpec) -> str:
        """워커에 job을 제출하고 즉시 시작. (workspace_id == job_id) 반환.

        구현은 다음을 묶어 수행한다:
          1. cq create_job(name, command, requirements)
          2. cq create_run(job_id, worker_id)
          3. spec.code + spec.aux_files + cq_config.json(spec.config)를 워크스페이스에 기록
             (로컬 워커=파일 시스템 직접, 원격 워커=cq write_file)
          4. cq control_job(start)
        """

    def poll(self, job_id: str, timeout: int) -> tuple[bool, dict, str]:
        """완료 대기. (succeeded, metrics, status_text) 반환.

        metrics는 cq get_status의 stdout 파싱(정렬 JSON 또는 @metric= 정규식).
        timeout 초과 시 (False, {}, "[TIMEOUT]") 반환 — 예외 던지지 않음(dispatch가 stderr 회수).
        """

    def download(self, job_id: str, path: str) -> str | None:
        """워크스페이스의 파일을 회수. 없거나 실패 시 None.

        path는 워크스페이스 루트 기준 상대 경로(예: "describe.json", "train_err.log").
        로컬 워커는 파일 시스템 직접 read, 원격 워커는 `cq download` 또는 NATS 회수.
        """

    def tail_stderr(self, job_id: str, n_lines: int = 50) -> str:
        """train_err.log의 마지막 N줄. 없으면 빈 문자열. ★에이전트 자기수정 입력(V5/V11).

        download("train_err.log") 결과의 tail이지만, 별도 메서드로 둔 이유: 구현이 옵션
        가질 수 있음(원격은 큰 로그 전체 download 비효율 → tail만 가져오는 빠른 경로).
        """

    def close(self) -> None:
        """리소스 정리(MCP stdio subprocess 종료 등). 컨텍스트 매니저로도 노출 가능."""
