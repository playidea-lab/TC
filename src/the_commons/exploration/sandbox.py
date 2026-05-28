"""V8 Sandbox — agent-authored 코드의 사전 정적 검사 (디스패치 전).

목적: GPU 비용 지불 전 명백한 reward-hacking 패턴 차단. **완전한 sandbox 아님** —
프로세스 격리·파일 시스템 ACL은 별도 (D4 prep 또는 운영 인프라).

규칙 (block = 디스패치 거부):

  1. `syntax_error`          — code가 py_compile 안 됨
  2. `prepare_monkeypatch`   — `prepare.<attr> = ...` 또는 `setattr(prepare, ...)`
                                (evaluator를 갈아치우는 가장 직접적 경로)
  3. `evaluate_redefine`     — `def evaluate_bpb` 또는 `evaluate_bpb = ...` top-level
                                (재정의로 평가 우회)
  4. `score_outside_adapter` — `@score=` 출력이 어댑터 마커보다 *앞에* 나옴
                                (어댑터는 train.py 끝에 자동 append되는 유일한 정당
                                emitter — 에이전트가 직접 emit하면 *위조* 의심)
  5. `val_data_access`       — validation 샤드 직접 read (shard_06542 또는
                                `~/.cache/autoresearch/data/` 경로)

알려진 빈틈 (정적 검사로 못 잡음):
  - `eval`/`exec`로 런타임 코드 실행
  - `subprocess`로 셸 우회해 val 데이터 read
  - `importlib`로 정적 AST 검사 우회
  → 진짜 방어 = 런타임 격리 + 파일 시스템 ACL (별 인프라). 이 모듈은 *1차 방어선*.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

# 어댑터가 append할 때 박는 마커(profile materialize 함수가 보장).
ADAPTER_MARKER = "# --- explore-loop adapter"

# val 샤드 경로 패턴 — autoresearch prepare.py VAL_SHARD=6542 + climbmix 캐시 구조.
_VAL_PATTERNS = (
    re.compile(r"shard_06542"),
    re.compile(r"\.cache/autoresearch/data"),
    re.compile(r"VAL_FILENAME"),
)


@dataclass(frozen=True)
class Violation:
    rule: str            # rule id
    severity: str        # "block" | "warn"
    message: str
    line: int = 0        # 1-based, 0=unknown


def check_code(code: str) -> list[Violation]:
    """모든 정적 규칙 적용. 빈 list = 디스패치 OK."""
    violations: list[Violation] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [Violation("syntax_error", "block", str(e), e.lineno or 0)]

    violations.extend(_check_prepare_monkeypatch(tree))
    violations.extend(_check_evaluate_redefine(tree))
    violations.extend(_check_score_outside_adapter(code))
    violations.extend(_check_val_data_access(code))
    return violations


def is_blocked(violations: list[Violation]) -> bool:
    return any(v.severity == "block" for v in violations)


def violations_to_dict(violations: list[Violation]) -> list[dict]:
    return [{"rule": v.rule, "severity": v.severity,
             "message": v.message, "line": v.line} for v in violations]


# ----- Rules -----------------------------------------------------------------


def _check_prepare_monkeypatch(tree: ast.AST) -> list[Violation]:
    """`prepare.<attr> = ...` 또는 `setattr(prepare, ...)` 차단."""
    out: list[Violation] = []
    for node in ast.walk(tree):
        # prepare.X = ...
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "prepare"):
                    out.append(Violation(
                        "prepare_monkeypatch", "block",
                        f"prepare.{tgt.attr} 재할당 금지 (evaluator 우회)",
                        node.lineno))
        # setattr(prepare, ...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if (node.func.id == "setattr" and len(node.args) >= 1
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "prepare"):
                out.append(Violation(
                    "prepare_monkeypatch", "block",
                    "setattr(prepare, ...) 금지 (evaluator 우회)",
                    node.lineno))
    return out


def _check_evaluate_redefine(tree: ast.AST) -> list[Violation]:
    """top-level `def evaluate_bpb` 또는 `evaluate_bpb = ...`."""
    out: list[Violation] = []
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "evaluate_bpb":
                out.append(Violation(
                    "evaluate_redefine", "block",
                    "evaluate_bpb 재정의 금지", node.lineno))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "evaluate_bpb":
                    out.append(Violation(
                        "evaluate_redefine", "block",
                        "evaluate_bpb top-level 재할당 금지", node.lineno))
    return out


def _check_score_outside_adapter(code: str) -> list[Violation]:
    """`@score=` emit이 어댑터 마커보다 앞 라인에 나오면 차단.

    어댑터(profile materialize 산출)만이 정당한 @score emitter. 그 앞에 @score를
    출력하는 코드 = 에이전트가 위조한 점수일 가능성.
    """
    lines = code.splitlines()
    marker_line = next((i for i, ln in enumerate(lines, start=1)
                        if ADAPTER_MARKER in ln), None)
    if marker_line is None:
        # 어댑터 자체가 없으면 검사 대상 외 (테스트 등)
        return []
    out: list[Violation] = []
    score_re = re.compile(r'@score\s*=')
    for i, ln in enumerate(lines[:marker_line - 1], start=1):
        if score_re.search(ln):
            out.append(Violation(
                "score_outside_adapter", "block",
                f"@score emit이 어댑터(line {marker_line})보다 앞 (line {i})",
                i))
    return out


def _check_val_data_access(code: str) -> list[Violation]:
    """val 샤드 경로 직접 read 차단 (단순 substring/regex)."""
    out: list[Violation] = []
    for pat in _VAL_PATTERNS:
        for m in pat.finditer(code):
            line = code.count("\n", 0, m.start()) + 1
            out.append(Violation(
                "val_data_access", "block",
                f"val 데이터 경로 직접 참조 금지: {pat.pattern!r}",
                line))
    return out


__all__ = [
    "Violation", "check_code", "is_blocked", "violations_to_dict",
    "ADAPTER_MARKER",
]
