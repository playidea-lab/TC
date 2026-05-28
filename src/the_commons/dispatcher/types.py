"""dispatcher_v2 데이터 계약 — JobSpec, JobResult, RunStatus.

V5(stderr_tail 1급 시민): JobResult.stderr_tail이 에이전트 자기수정의 입력이다. 누구도
optional/감출 수 없게 데이터클래스 필드로 명시 — 인터페이스에 박는 게 ②의 본질.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JobSpec:
    """워커에 보낼 job 명세. 모든 필드 명시(암시 default 없음 — 누락 발견 쉽게).

    code: train.py 본문(profile materialize 산출 또는 정적 파일 읽기 결과).
    aux_files: name→content (예: autoresearch는 {"prepare.py": <vendored content>}).
    config: cq_config.json에 들어갈 next_config(pcq.config() 주입). autoresearch는 {}.
    command: 워커 shell command. 비면 caller(또는 wrapper)가 default를 미리 채워야.
    monitor/metric_keys: cq best 판정/회수 metric 키.
    requirements: pip reqs(`uv run --with`).
    timeout: poll 최대 대기(초).
    """

    name: str
    code: str
    aux_files: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    monitor: str = ""
    metric_keys: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    timeout: int = 1200


@dataclass
class JobResult:
    """디스패치 결과. stderr_tail은 1급 시민 — 실패해도 채워서 반환(에이전트 자기수정 입력)."""

    job_id: str
    workspace_id: str                # cq에서는 job_id == workspace_id
    success: bool
    fitness: float | None            # describe.best_value 우선, metrics[monitor] 폴백
    metrics: dict[str, Any] = field(default_factory=dict)
    describe: dict[str, Any] | None = None
    stderr_tail: str = ""            # ★ V5: 에이전트 자기수정 입력 (1급 시민)
    status_text: str = ""            # cq get_status 원문(디버그용)
    error: str = ""                  # 실패 한 줄 요약


@dataclass
class RunStatus:
    """poll() 중간 결과(현재는 미사용, 향후 progress 추적용 placeholder)."""

    state: str                       # "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | ...
    progress: float = 0.0
