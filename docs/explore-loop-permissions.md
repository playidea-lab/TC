# explore-loop 자율 운영 권장 권한 (R1 D4 / V13)

> `/loop`으로 explore-loop을 무인 자율 실행할 때 권한 프롬프트로 자율이 끊기지 않게 하는
> 권장 `.claude/settings.json` 설정. 보안상 *너가 직접 검토하고 적용*해야 한다(자동 적용
> 금지 — 권한 확대는 self-modification).

## 권한 확장 방법 (셋 중)

1. **수동**: 아래 JSON을 `.claude/settings.json`에 합쳐서 추가.
2. **`/fewer-permission-prompts` 스킬**: Claude Code 내 실행 → 최근 트랜스크립트에서 흔히 거부되는 액션 추출 → 권장 allow 추가.
3. **`/update-config` 스킬**: "explore-loop 자율 운영용 권한 추가해줘" 같은 요청으로 정밀 추가.

## 권장 `.claude/settings.json` (병합 또는 신설)

```json
{
  "permissions": {
    "allow": [
      "mcp__the-commons__tc_explore_recommend_action",
      "mcp__the-commons__tc_explore_report_result",
      "mcp__the-commons__tc_explore_archive_state",
      "mcp__the-commons__tc_explore_build_query",
      "mcp__the-commons__tc_dispatch",
      "mcp__the-commons__tc_recommend",
      "mcp__the-commons__tc_ingest_pcq",
      "mcp__the-commons__tc_get_evidence",
      "mcp__the-commons__tc_knowledge",
      "mcp__the-commons__tc_lineage",
      "mcp__the-commons__tc_recent_attempts",
      "mcp__cq__get_status",
      "mcp__cq__bash",
      "mcp__cq__cq_help",
      "mcp__cq__create_job",
      "mcp__cq__create_run",
      "mcp__cq__control_job",
      "mcp__cq__write_file",
      "mcp__cq__read_file",
      "mcp__cq__list_files",
      "WebSearch",
      "WebFetch",
      "Bash(uv run pytest *)",
      "Bash(uv run python *)",
      "Bash(uv run python -m py_compile *)",
      "Bash(git status*)",
      "Bash(git diff*)",
      "Bash(git log*)",
      "Bash(git branch*)",
      "Bash(git fetch*)",
      "Bash(grep *)",
      "Bash(ls *)",
      "Bash(head *)",
      "Bash(tail *)"
    ]
  }
}
```

## 권한별 이유

### 핵심 (autonomous 라운드 필수)
- `tc_explore_recommend_action` — 매 라운드 controller 추천 받기
- `tc_explore_report_result` — placement + attribution log
- `tc_explore_archive_state` — 진행상황 점검
- `tc_explore_build_query` — Explosion 모드 쿼리 합성
- `tc_dispatch` — 코드 GPU 디스패치

### TC 도구 (이미 사용 중인 것 포함)
- `tc_recommend`/`tc_ingest_pcq`/`tc_get_evidence`/`tc_knowledge`/`tc_lineage`/`tc_recent_attempts` —
  사서 기능 (라운드 외 일반 활용도)

### cq 도구 (원격 워커 조작)
- `cq_get_status` — 워커/잡 상태 확인
- `cq_bash` — 워커 시스템 명령(읽기 전용 nvidia-smi 등)
- `cq_create_job`/`cq_create_run`/`cq_control_job` — 잡 생애주기
- `cq_write_file`/`cq_read_file`/`cq_list_files` — 원격 파일 I/O

### 보조
- `WebSearch`/`WebFetch` — Explosion 모드 + 일반 조사
- `Bash(uv run *)` — 테스트·py_compile (구체 패턴으로 제한, `Bash(*)` 같은 와일드카드 금지 권장)
- `Bash(git *)` 읽기 전용 (status/diff/log/branch/fetch) — git push/commit은 의도적으로 제외

## 빠진 것 (의도적)

- **`Write`/`Edit` 전체 허용 금지** — 에이전트가 explore_tier2(구조 변경 저술) 모드에서
  파일 수정할 때마다 confirm 받게 두는 게 안전. 자율성을 약간 깎지만, 잘못된 코드 변경의
  실수 비용이 큼.
- **`Bash(git push*)`, `Bash(git commit*)`, `Bash(gh pr *)` 제외** — 외부 발행·되돌리기 어려운
  액션은 confirm 유지.
- **`mcp__cq__delete_job`/`update_job` 제외** — 의도 없이 잡 삭제·수정 방지.
- **`Bash(rm *)`, `Bash(sudo *)` 등 파괴적 명령 절대 미포함** — `deny`로도 명시할 수 있음.

## 확인 방법

설정 적용 후 `/loop 30m "/explore-loop-round autoresearch --remote"` 같은 명령으로 짧게 돌려보면서
권한 프롬프트가 뜨는지 확인. 뜨면 위 allow에 패턴 추가.

## 참고

- plan: `~/.claude/plans/gentle-chasing-fern.md` (Phase D4)
- idea: `.cq/runtime/ideas/explore-loop-v3-agent-in-loop.md` (V13)
- per-round 절차: `cq-ops/skills/explore-loop-round/SKILL.md`
