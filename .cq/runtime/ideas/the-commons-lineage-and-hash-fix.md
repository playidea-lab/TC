# The Commons — Lineage Forward-Compat + content_hash UNIQUE 정정

> 재감사 사이클 산출물. (1) vision카드 #7이 약속한 L2 lineage 엣지가 코드에
> 부재 — forward-compat 슬롯으로 예약(matchmaker는 안 읽음). (2) Stage 2
> envelope 마이그레이션이 InMemoryStore의 content_hash 유일성은 풀었으나 PG
> `evidence.content_hash UNIQUE` 제약은 그대로 — R10 의미 위반(같은 pcq_record를
> 다른 evidence_id로 ingest 시 PG가 거부). 두 결정을 마이그레이션 005 한 묶음.

## 왜 이 사이클인가

사용자 재감사(/pi 한번더 체크)에서 두 가지가 같이 잡혔다:

1. **lineage 엣지 부재**: vision #7은 L2 append-only에 derives_from·reproduces·
   contradicts·compared_to 엣지 자리를 약속. 코드의 `reciprocity_event.event_type`은
   verdict 측정용 3종(loop_closure/promote/contradicts)만. 매치메이커는 evidence를
   고립된 점으로만 봄(lineage 그래프 없음). 비전이 약속한 "음성·실패가 검색공간을
   좁힌다 — lineage 1급" 약속이 정책 문구로 머묾.
2. **content_hash UNIQUE 제약 vs R10**: pcq integrity는 envelope-독립 hash —
   같은 pcq_record가 다른 evidence_id로 두 번 ingest되는 게 *합법*. Stage 2
   InMemoryStore는 풀었지만 PG는 제약 그대로 → 실제 버그.

## 결정화한 설계

### DD1. lineage 가치는 corpus-density-gated — 지금은 forward-compat 예약만

lineage 엣지가 매치메이커에 추가하는 신호(4종 분석):
- **reproduces**: 재현된 evidence의 metric은 미재현보다 신뢰도↑ (posterior 가중)
- **contradicts**: X를 부정한 Y가 있으면 X down-weight (지금은 Beta가 X·Y를
  독립 관측으로 처리, 관계 사라짐)
- **derives_from**: hyperparam 파생 체인을 매치메이커가 *이미 걸어본 경로*로
  인식, 직교 방향 추천
- **compared_to**: 같은 맥락서 A/B된 두 recipe는 무관 실행보다 강한 비교 신호

가치 곡선: **코퍼스 밀도(≈서비스화 게이트 C2 임계, retirement_real_threshold=3)에
gated**. 빈 코퍼스 → 0, 같은 recipe×문제에 N≥3~5 쌓이면 의미. 초기 0건이라 *지금*
matchmaker가 lineage를 읽는 가치는 ≈0.

→ **forward-compat 예약**: 스키마·저장은 day-one에 박고 matchmaker는 v0.2까지
안 읽음. producer 인터페이스(cq M4)가 *한 번만* 확정됨 — 경제적.

### DD2. 형태 = (A)+(b) — envelope lineage 필드 + 새 lineage_edge 테이블

**API (A)**: TC envelope 최상위 `lineage:[{type, target_evidence_id}]` 필드.
R10 정합(lineage는 evidence 간 관계라 TC 소유, pcq_record 안 아님 — TC_RECONCILIATION §4
와 일치). cq M4의 single-seam(/ingest 한 번 호출)으로 evidence+lineage 한 트랜잭션.

**Storage (b)**: 새 `lineage_edge` 테이블 (마이그레이션 005):
- `edge_id BIGSERIAL PRIMARY KEY`
- `source_evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id)`
- `target_evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id)`
- `edge_type TEXT NOT NULL` (enum: derives_from/reproduces/contradicts/compared_to)
- `origin TEXT NOT NULL` (internal/external)
- `metadata JSONB`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- append-only by convention (DB enforce는 v0.2 — DD5 한계)

reciprocity_event는 **무손상 유지** — verdict 측정 신호 보존(C3 산정 포함).
의미 중복(promote ≈ reproduces-with-pass) 알려진 채로 두고, lineage_edge가
정전이고 reciprocity_event가 그 view/projection이냐 분리냐는 **v0.2 통합 사이클**.

### DD3. content_hash UNIQUE 제거 — 같은 마이그레이션 005에 묶음

`ALTER TABLE evidence DROP CONSTRAINT evidence_content_hash_key`. PostgresStore의
`except UniqueViolation → EvidenceAlreadyExistsError` 로직은 *evidence_id PK*
충돌에만 작동하도록 좁힘. content_hash는 무결성 증명일 뿐 유일성 키 아님(R10).

### DD4. matchmaker는 lineage 안 읽음 (이 사이클 한정)

infogain reranker 변경 없음. lineage가 *지금* 추천 결정에 영향 0. 코퍼스가 자라
v0.2 사이클에서 matchmaker가 lineage 입력을 추가하는 게 자연 다음 단계.

### DD5. 발견된 잔여 갭은 문서 표기로만 (이 사이클 외)

- **L2 immutability DB-enforce 부재**: append-only by convention, 물리적 강제 없음
  → 문서 한계 명시(README/llms.txt)
- **운영자 변조 audit trail 부재**: 거버넌스 정정으로 변조 가능, 변조 detect는
  corpus export round-trip 게이트뿐 → 별도 거버넌스-정직성 사이클로 분리
- **verifier read-path 미검증**: synthetic_source.verifier가 read 시점 server-derive
  되는지 검증 부재 → 이 사이클에 *간단 테스트 추가*(작은 추가 작업)
- **embedding stale 자동 재계산 없음**: embedding_template_ver 컬럼은 있지만
  trigger 없음 → v0.2

## 요구사항 (EARS)

- **LE1** WHEN ingest body가 envelope `lineage:[{type, target_evidence_id}]`을
  포함할 때, attribution_validator가 각 엣지의 target_evidence_id 존재성
  + type ∈ {derives_from, reproduces, contradicts, compared_to} 검증한다.
- **LE2** WHEN 검증된 lineage가 있을 때, ingest는 evidence row INSERT와 *같은
  트랜잭션*으로 lineage_edge에 N개 row append한다.
- **LE3** WHILE lineage 없이 들어온 envelope이 통과될 동안 정상 ingest 흐름은
  영향 없음 (lineage Optional).
- **LE4** WHEN 같은 pcq_record가 다른 evidence_id로 두 번 ingest될 때, DB는
  evidence_id PK 충돌이 없는 한 *받아들인다* (content_hash 중복 합법, R10).
- **LE5** WHILE matchmaker가 추천을 산정할 동안, lineage_edge는 *읽지 않는다*
  (forward-compat 예약 — DD4).
- **LE6** WHEN 응답 또는 `/evidence/{id}` GET에서 synthetic record를 반환할 때,
  `synthetic_source.verifier`가 read 시점 server-derive로 채워진다(또는 None).

## 범위 외 (v0.2)

- matchmaker가 lineage_edge 읽기 (corpus 밀도 gated)
- lineage_edge ↔ reciprocity_event 의미 통합 (정전/view 결정)
- L2 DB-enforce(append-only 트리거·권한)
- 운영자 변조 audit log (거버넌스 별도 사이클)
- embedding stale 자동 재계산
- L2 통합 후 lineage 기반 정보이득 reranker 확장

## 리스크

| 리스크 | 심각도 | 대응 |
|--------|--------|------|
| 의미 중복(promote≈reproduces-pass) 으로 v0.2 통합 비용 ↑ | 중 | 알려진 한계 명시, 두 테이블 어느 한쪽이 다른 쪽 superset이라 통합 시점 명확 |
| forward-compat 예약을 "있다"로 오인 → 매치메이커 lineage 활용 기대 | 중 | 문서·llms.txt에 "matchmaker는 v0.1엔 lineage 안 읽음" 명시 |
| content_hash UNIQUE 제거 후 진짜 중복(같은 evidence_id 재제출) 검출 약화 | 낮 | evidence_id PK가 그 케이스 막음. content_hash 중복 자체는 합법 |
| L2 append-only가 정책뿐 | 중 | 명시·v0.2 ops 사이클 |

## 다음 사이클 후보

1. **이 사이클 구현** (마이그레이션 005 + ingest 수용 + verifier read 테스트)
2. matchmaker lineage 읽기 (corpus 밀도 트립 후 v0.2)
3. lineage_edge ↔ reciprocity_event 통합 (v0.2)
4. 거버넌스-정직성 사이클 (audit log, L2 enforce)

## 관련

- [[the-commons-vision]] #7 — L2 append-only lineage 약속의 첫 명시
- [[the-commons-role-definition]] — 매치메이커 정보이득 목적함수 (lineage 활용 미래)
- [[the-commons-productization-gate]] — C2 corpus density (lineage 가치 활성 트립)
- pcq `docs/TC_RECONCILIATION.md` §4 — R10 (lineage는 TC envelope 소유)

---

*Generated by /pi on 2026-05-20 — 재감사 사이클: lineage forward-compat (A)+(b) + content_hash UNIQUE 정정, 단일 마이그레이션 005 묶음*
