# tc-spring-cleaning

> 도서관 단순성 회복 — 잔재 3건 정리. ~200 LOC 삭제, 0 추가.
> 의도와 현실 불일치 제거 + 정직성 확보.

---

## 한 문장 요약

`content_hash.py`의 "Stage 2 제거 예정" 잘못된 메모를 책임 명확화로 정정, `docs/pcq-2.x.md` (proposal NOT canonical) 완전 삭제 + 4 surface 링크 정정, ruff F401 2건 + integration 14건 envelope 마이그레이션 cleanup.

---

## 배경 / Why now

audit 발견:

1. **content_hash.py docstring 거짓말** — 구 API(`compute_content_hash`/`verify_content_hash`)가 "Stage 2에서 envelope·호출부 마이그레이션과 함께 제거 예정"이라고 했으나, 실제로는 두 API가 *다른 책임* + *다른 canonical form* + *다른 hash*:
   - `compute_integrity` (pcq R9): indent=2, 13 leaf allowlist, pcq build_integrity_object byte-parity
   - `compute_content_hash` (TC NDJSON corpus): compact `separators=(",", ":")`, attribution.content_hash 검증용
   - 두 hash는 byte-divergent — 통합 불가능.

2. **docs/pcq-2.x.md proposal 살아있음** — 정본이 pcq spec/ (또는 vendoring `docs/vendor/pcq/SPEC-pcq-2.x.md`)로 확정됐는데도 historical TC proposal이 그대로 + 4 surface에 "NOT canonical" 라벨 + index.html에서 2개 링크. 정직 표기는 했지만 incongruent.

3. **ruff F401 unused imports 2건** — auto-fixable.

4. **integration 14건 envelope 마이그레이션 잔여물** — Stage 2 envelope sweep 시점에 명시적으로 미루기로 한 dangling work.

---

## 결정 (DD)

### DD1: content_hash.py — 책임 명확화 (통합 불가)
- `compute_integrity` / `verify_integrity` (pcq R9, indent=2, 13 leaf) — 유지
- `compute_content_hash` / `verify_content_hash` (TC NDJSON corpus, compact, attribution.content_hash 검증) — **유지**, docstring을 *별도 책임*으로 정정
- "Stage 2에서 제거 예정" 메모 삭제 — 거짓이었음 (두 API 책임 다름)
- 명명은 그대로 (호출부 마이그레이션 비용·hash 변경 회피)

### DD2: docs/pcq-2.x.md — 완전 삭제
- 파일 자체 `git rm` — historical proposal 잔재
- 정본 위치는 이미 4 surface에 명시 (playidea-lab/pcq spec/ + vendoring `docs/vendor/pcq/SPEC-pcq-2.x.md`)
- 4 surface 링크 정정:
  - `docs/llms.txt`: pcq_2x_proposal 링크 삭제
  - `docs/agent-manifest.json`: `resources.pcq_2x_proposal` 항목 삭제
  - `docs/index.html`: 2개 링크 삭제 또는 vendor/pcq/SPEC-pcq-2.x.md로 redirect
  - `README.md`: `[docs/pcq-2.x.md]` 참조 삭제

### DD3: ruff F401 — auto-fix
- `uv run ruff check --fix tests/`

### DD4: integration 14건 envelope 마이그레이션
- Stage 2 envelope sweep 잔여물 — `tests/integration/*`이 pcq record를 *flat* 형식으로 작성하는데 TC envelope은 `{evidence_id, tier, outreach_origin, pcq_record: {...}}` 구조 강제
- 14 파일 모두 envelope wrapping 적용
- 만약 작업 크기가 너무 크면 별 사이클로 분리 (idea card 보존)

---

## EARS 요구사항

### Ubiquitous
- The system shall maintain `compute_content_hash` and `compute_integrity` as distinct APIs with clearly documented responsibilities.
- The system shall not reference `docs/pcq-2.x.md` in any source file or documentation.

### Event-Driven
- When a developer reads `content_hash.py`, the docstring shall accurately describe each function's responsibility (no false deprecation notice).

### Unwanted
- If `docs/pcq-2.x.md` exists in the repo, the cleanup is incomplete.
- If `ruff check` reports F401 errors, the cleanup is incomplete.

---

## 변경 범위

| 파일 | 변경 |
|---|---|
| `src/the_commons/library/content_hash.py` | docstring 정정 — "Stage 2 제거" 메모 삭제, 책임 명확화 |
| `docs/pcq-2.x.md` | **삭제** |
| `README.md` | `docs/pcq-2.x.md` 참조 항목 정정 (정본 위치만 명시) |
| `docs/llms.txt` | pcq_2x_proposal 링크 항목 삭제 |
| `docs/agent-manifest.json` | `resources.pcq_2x_proposal` 키 삭제 |
| `docs/index.html` | 2개 `pcq-2.x.md` 링크 삭제 또는 SPEC.md로 redirect |
| `tests/` (ruff F401) | unused imports auto-fix |
| `tests/integration/*.py` (14 파일) | envelope wrapping 적용 (별 사이클 분리 가능) |

---

## 검증

- 340/340 unit green 회귀 0
- ruff F401 0건
- grep `pcq-2.x.md`: 4 surface + 코드에서 0건 (vendor/pcq/PROVENANCE.md 내부 historical 참조는 예외 허용 — vendoring 문서)
- 14 integration 마이그레이션 시 별도 verify

---

## 리스크 / 미해결

| 리스크 | 완화 |
|---|---|
| `compute_content_hash` 호출부가 미래에 corpus format 변경 시 두 hash가 또 divergent 가능성 | docstring 명시 + 코드 주석으로 책임 경계 박음 |
| 14 integration 파일 마이그레이션 큰 작업 | 본 사이클 분리 옵션 — 코드 변경 0이면 별도 idea로 |

---

## 진행 방식

자동 구현 (plan → run → finish).
