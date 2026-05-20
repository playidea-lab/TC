# tc-pcq-2.x-reproducibility-pack-vendoring

> pcq v4.10.0 Reproducibility Pack을 TC envelope·mirror에 추가. additive only.
> R9/R10 경계 유지. matchmaker는 v0.2에서 활용.

---

## 한 문장 요약

pcq가 v4.10.0에서 추가한 `code` / `seeds` / `data_ref` 3 top-level 필드를 TC `PcqRecord`에 흡수하고, `content_hash.py` mirror의 `_INTEGRITY_HASHED_FIELDS`에 4 신규 leaf를 추가하고, `extra="allow"`로 전환해 미래 *unhashed* 필드도 자동 흡수하고, 4 doc surface에 R8 anti-overclaim 한 줄을 박는다.

---

## 배경 / Why now

- pcq v4.10.0 main 푸시 완료(28e2698). PyPI release.yml 트리거됨.
- cq M4가 pcq emit 시작하면 record에 `code/seeds/data_ref` 포함 → TC가 `extra="forbid"`로 거부하면 ingest 깨짐.
- content_hash mirror가 4 신규 leaf 모르면 `compute_integrity`/`verify_integrity` 결과가 pcq와 byte-divergence.
- 페이싱: **TC mirror 완료 *전* cq M4 emit 시작 금지**. 본 사이클이 cq M4 unblock의 dependency.

---

## 결정 (DD)

### DD1: Pydantic extra mode — R10 경계로 분리
- **Evidence envelope (TC scope, R10): `extra="forbid"` 유지.** evidence_id/tier/outreach_origin/synthetic_source/lineage/pcq_record/deprecated 외 미지 필드 차단 (TC 자체 스키마 무결성).
- **PcqRecord + 모든 nested(Intent/DataFingerprint/Config/Metrics/WorkerSpec/Attribution/Integrity/Code/DataRef): `extra="allow"` 전환.** pcq R6 additive 본질 받음.
- **이유**: pcq의 미래 *unhashed* top-level/nested 필드 추가 시 TC sync 사이클 강제 없앰. `__pydantic_extra__`에 보존되어 model_dump 재직렬화 시 canonical form byte-parity 유지(content_hash mirror 보전).
- **반려된 대안**: `extra="ignore"` — drop 시 재직렬화 byte-divergence로 mirror 깨짐.

### DD2: `code.scope` 구조화 (Literal kind 강제)
- `Code` 모델: `content_sha256: str`, `scope: Scope` (둘 다 present 시 required).
- `Scope` 모델: `kind: Literal["entry_script", "file_list", "repo_subset"]` required, `files: list[str] | None`, `root: str | None`.
- pcq schema가 `code` present 시 `scope.kind` 항상 present 강제. `scope: null` 안 됨.
- `code` 자체는 PcqRecord-level Optional (additive).

### DD3: `_INTEGRITY_HASHED_FIELDS` 13 leaf (기존 9 + 신규 4)
- 신규 4: `code.content_sha256`, `code.scope`, `seeds`, `data_ref.content_sha256`.
- anti-recursion 보존: `attribution.signature`, `integrity.*` 제외 유지.
- **absent-leaf drop**: pcq build_integrity_object 의미론 — None resolve leaf는 canonical subset에서 완전 drop (`'path': null` 포함 X). PHI stripped된 `data_ref.content_sha256`과 *absent* 필드가 동일 hash 동작.

### DD4: 적대 입력 18건 (기존 9 + 4.10.0 신규 9) 회귀
- pcq의 `test_integrity_hash_identical_when_data_ref_absent_vs_data_ref_content_sha_stripped` 시나리오를 TC `tests/unit/test_content_hash.py`에 미러링.
- 2 독립 구현이 같은 hash 내면 = byte-parity 상호 검증.
- 신규 9 시나리오: code-absent / seeds-absent / data_ref-absent / data_ref.content_sha256-stripped / scope.kind 변경 / scope.files 순서변경 / seeds.<name> int↔str / data_ref.size_bytes 변경 / 전부-absent.

### DD5: 4 doc surface R8 anti-overclaim 한 줄
- README.md, docs/llms.txt, docs/index.html, docs/agent-manifest.json.
- 정확 문구: **"pcq makes evidence reproducible, not execution-attested."**
- Link: `https://github.com/playidea-lab/pcq/blob/main/spec/SPEC.md` (조직 `playidea-lab` 주의 — pcq 측 정정 받음).
- 한국어 surface: 영어 그대로 인용 또는 의역 ("pcq는 evidence를 *재현 가능*하게 만들지, *실행을 증명*하지 않는다.").
- 기존 "evidence"·"reproducibility" 문구에 "execution proof" 함의 audit.

---

## EARS 요구사항

### Ubiquitous (시스템 불변)
- The system shall accept pcq 2.x records with or without `code`, `seeds`, `data_ref` fields (additive optional).
- The system shall preserve unknown top-level fields inside `pcq_record` and its nested objects through ingest → store → retrieve (byte-parity round-trip).
- The system shall compute `content_hash` over 13 hashed leaves identical to pcq's `build_integrity_object` output.

### Event-Driven
- When `code` is present, the system shall require `code.content_sha256` and `code.scope.kind ∈ {entry_script, file_list, repo_subset}`.
- When `data_ref.content_sha256` is None (PHI-stripped), the system shall produce a content_hash byte-identical to a record where `data_ref.content_sha256` leaf is absent.
- When ingesting a record with future unknown nested fields (not in TC's PcqRecord schema), the system shall accept and preserve them via `__pydantic_extra__`.

### Unwanted
- If `Evidence` envelope contains unknown top-level fields (TC scope), the system shall reject with HTTP 422.
- If `code` is present without `scope.kind`, the system shall reject with HTTP 422.
- If TC mirror produces content_hash divergent from pcq's reference implementation on the 18 adversarial inputs, the test suite shall fail.

### Optional (future)
- If a future pcq cycle adds new leaves to `integrity.hashed_fields`, TC operations shall monitor pcq CHANGELOG and trigger a TC mirror sync cycle (manual, not automatic — record-declared hashed_fields trust is rejected per R8).

---

## 변경 범위

| 파일 | 변경 |
|---|---|
| `src/the_commons/library/models.py` | `Code` / `Scope` / `Seeds` (dict alias) / `DataRef` 모델 추가. `PcqRecord` + Intent에 `extra="allow"` 전환. `PcqRecord`에 3 optional 필드 추가. |
| `src/the_commons/library/content_hash.py` | `_INTEGRITY_HASHED_FIELDS`에 4 leaf 추가. anti-recursion 그대로. |
| `tests/unit/test_content_hash.py` | 적대 18 입력 (기존 9 + 신규 9). |
| `tests/unit/test_models.py` | extra="allow" 동작 + Code/Scope/DataRef 검증 (positive/negative). |
| `tests/unit/test_ingest_4_10.py` (신규) | end-to-end ingest with code+seeds+data_ref. |
| `README.md`, `docs/llms.txt`, `docs/index.html`, `docs/agent-manifest.json` | R8 한 줄 + link 추가. v0.1 한계 섹션 보강. |
| `docs/TC_RECONCILIATION.md` (이미 vendoring 소스 명시) | 4.10.0 항목 추가 — 변경분 + git tag 핀. |
| `pyproject.toml` (선택) | 본 사이클은 spec/schemas vendoring만, pcq 라이브러리 import 안 함. cq M4 정합과 함께 다음 사이클에서. |

---

## 검증

- **300+ unit green** (현재 300 + 신규 ~12 = 312 목표), 회귀 0.
- **18 적대 입력 byte-parity** 통과.
- **ingest 4 ingest 시나리오** (3 신규 필드 모두 / 부분 / 미지 필드 / PHI stripped) HTTP 200.
- **ruff clean**, mypy clean (해당 영역).
- **4 surface 일관성**: "pcq makes evidence reproducible, not execution-attested." grep으로 4건 확인.

---

## 리스크 / 미해결

| 리스크 | 완화 |
|---|---|
| pcq future hashed_fields 추가 시 TC mirror sync 누락 | RELEASE_NOTES.md watch + CHANGELOG monitor 운영 룰. v0.2 동적 resolve는 R8 위배라 보류. |
| `extra="allow"`로 record 변조(악성 필드 삽입) | content_hash mirror가 변조 검출. unhashed 미지 필드는 의미적 영향 0(matchmaker가 안 읽음). |
| Pydantic model_dump가 `__pydantic_extra__` 순서 불안정 | canonical form은 `sort_keys=True`로 정렬 — 안정. |
| flat keys(`seeds_main` 등) integrity 미포함 (pcq 측 확정) — TC mirror에서 추적 시도 시 실수 | mirror nested-only 명시 docstring. |
| matchmaker v0.1이 `code`/`seeds`/`data_ref`를 ranking에 안 씀 | forward-compat 의도. v0.2 backlog에 "reproduce-verify before promote" 명시. |

---

## v0.2 backlog (이번 사이클이 시드)

1. **Reproduce-verify before promote**: `code.content_sha256 + seeds + data_ref.content_sha256` 일치 시 promote, 불일치 시 contradicts event. 트리거 조건·샘플링·tolerance 전부 TC 자체 설계. (intent.tolerance 재프레이밍과 자연 결합.)
2. **PHI 분기 매치메이커 정책**: `data_ref` 존재 + `content_sha256=None` → "재현 검증 불가" 마킹. hash로는 absent와 구분 안 됨 → presence inspection 코드 추가.
3. **intent.tolerance 재프레이밍**: 의견 → stochastic variance fact. pcq 다음 사이클에서 spec 변경 가능성, TC는 그 다음에 흡수.

---

## 관계

- pcq v4.10.0 (28e2698, main, tag `v4.10.0`) — vendoring 소스.
- TC `tc-pcq-2.x-envelope-stage-2-3-sweep` (T-V2-001, completed) — 본 사이클의 직전.
- TC `the-commons-lineage-and-hash-fix` (T-LE-001/002/003, completed) — 본 사이클의 직전.
- cq M4 — 본 사이클이 unblock하는 dependency.

---

## 진행 방식

자동 구현 (plan → run → finish 전체 자동, `--from-pi --auto-run`).
