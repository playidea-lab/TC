# Vendored pcq 2.x — Provenance

> ⚠️ **이 디렉토리는 read-only vendored 사본이다. 수정 금지.**

- **출처 repo**: github.com/playidea-lab/pcq (로컬 `/Users/changmin/git/cq_ml`)
- **commit**: `5e86bee` (T-PCQ2X-8)
- **package version**: pcq v4.9.0
- **contract_version**: `"2.0"`
- **채취일**: 2026-05-19

## 정본 규칙

**pcq `spec/`가 pcq 2.x의 SINGLE canonical source다.** 이 디렉토리의 사본과
pcq `spec/`가 갈리면 **pcq `spec/`가 우선**한다. TC ingestion·schema 코드는
pcq `spec/`에 맞춰 갱신하지, 그 반대가 아니다.

## 사본 목록

| 파일 | 정본 경로 (pcq repo) |
|---|---|
| `pcq.describe_run.record.schema.json` | `spec/schemas/pcq.describe_run.record.schema.json` (generated — ground truth) |
| `SPEC-pcq-2.x.md` | `spec/SPEC.md` `## pcq 2.x Contract` ~ `## Non-Goals` 직전 발췌 (R9/R10/R12 포함) |

손으로 필드 정의를 베끼지 않는다 — generated schema가 ground truth.
참조 구현(hash byte-parity 미러 대상): pcq `src/pcq/contract.py`
`build_integrity_object` / `_INTEGRITY_HASHED_FIELDS` / `_resolve_dotted_path`.

핸드오프 노트 원본: pcq repo `docs/TC_RECONCILIATION.md`.

## 재-vendoring 절차

pcq spec/ 갱신 시: 위 두 파일을 새 commit에서 다시 복사하고 이 PROVENANCE의
commit/version/날짜를 갱신한 뒤, TC 코드를 정본에 맞춰 재조정한다.
