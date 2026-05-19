# pcq 2.x — superseded by vendored canonical

> ✅ **정본 확정 (2026-05-19, pcq v4.9.0 / commit `5e86bee`).**
> 이 문서의 옛 *제안(proposal)* 본문은 **폐기**되었고, pcq `spec/`의
> **정본**으로 대체되었다.

**정본 사본 위치 (TC vendored, read-only):** [`docs/vendor/pcq/`](vendor/pcq/)

- [`vendor/pcq/pcq.describe_run.record.schema.json`](vendor/pcq/pcq.describe_run.record.schema.json) — generated JSON Schema (ground truth)
- [`vendor/pcq/SPEC-pcq-2.x.md`](vendor/pcq/SPEC-pcq-2.x.md) — SPEC §pcq 2.x Contract (R9/R10/R12 포함)
- [`vendor/pcq/PROVENANCE.md`](vendor/pcq/PROVENANCE.md) — 출처·commit·정본 규칙

**규칙:** pcq `spec/`가 SINGLE canonical source. 이 사본과 갈리면 pcq
`spec/`가 우선. TC는 정본에 맞춰 갱신한다(그 반대 아님).

**핵심 변경 (옛 제안 대비):**
- 무결성 해시 = top-level `pcq_record.integrity.content_hash` (NOT
  `attribution.content_hash`). `attribution`은 행위자(WHO)로 무변경 —
  옛 제안의 키 충돌 해소됨.
- TC `Evidence` = envelope: `{evidence_id, tier, outreach_origin,
  synthetic_source, pcq_record:{<pcq 2.x run_record verbatim>}}`.
  evidence_id/tier/outreach_origin/synthetic_source만 TC 소유.
- 필드 매핑(R12): created_at→run_record 기존 timestamp,
  contributor_id→`attribution.operator`, pcq_version→top-level
  `contract_version`.
- additive(R6): 1.x record도 valid (부재 필드 = null).

TC vendoring 진행 메모: 메모리 `tc-pcq2x-canonical-ownership`.
