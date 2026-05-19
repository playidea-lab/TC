# pcq 2.x — Input Format **Proposal** for The Commons v0.1

> ⚠️ **정본 아님 (2026-05-19).** 이 문서는 TC가 *제안하는* 입력 형식이며
> **계약/정본이 아니다**. pcq 2.x **정본은 pcq repo의 `spec/`가 정의**하고
> TC는 그것을 **vendoring**한다. 이 제안과 정본이 갈리면 정본이 우선한다.
>
> **미해결 known issue — `content_hash` 키 충돌:** 본 제안은 무결성 해시를
> `attribution.content_hash`에 두는데, 이는 **pcq v4.4의 `attribution`
> (= 행위자: operator/author/committer)과 키 의미 충돌**이다. 무결성 해시는
> `attribution` 밑이 아니라 **별도 top-level 필드**로 분리되어야 한다.
> 최종 위치·이름은 pcq `spec/` 단일화의 산출물이며 TC는 그때 vendoring한다.
> 그 전까지 TC의 Evidence 모델·content_hash 코드는 *동결*(단독 재정의 금지).
> cq M4(2.x emission)는 이 단일화 *이후*다.

## 왜 2.x인가

pcq 1.x는 *실험 evidence의 기본 schema*를 제공했지만 TC v0.1에 필수적인 다음
세 가지가 누락되었다:

1. **intent 3필드** — goal / expected_baseline / tolerance. "성공/실패의 정의"
   가 evidence에 포함되어야 null·negative result가 1급 자산이 된다.
2. **data fingerprint** — modality / sample count band / 통계 모먼트. 매치메이커
   retrieve의 핵심 신호이자 PHI 차단의 표면.
3. **synthetic tier + attribution** — LLM-distilled evidence의 별도 tier 표식과
   strict attribution. retire 가능 + transparency 보장.

이 셋이 들어가면 자연스럽게 v2.0으로 minor → major bump.

## Top-level record

```json
{
  "evidence_id": "ev-...",
  "tier": "real" | "synthetic",
  "outreach_origin": "internal" | "external",

  "intent": { ... },
  "data_fingerprint": { ... },
  "config": { ... },
  "metrics": { ... },
  "worker_spec": { ... },
  "manifest": { ... },
  "validation_report": { ... },

  "attribution": { ... },
  "synthetic_source": { ... } | null
}
```

### 필드별 요구사항

| 필드 | 필수 | 설명 |
|---|---|---|
| `evidence_id` | ✅ | 시스템 발급 ID (예: `ev-a1b2c3`). content_hash와 1:1 |
| `tier` | ✅ | `real` (실제 실행) / `synthetic` (LLM 증류) |
| `outreach_origin` | ✅ | `internal` (PI Lab) / `external` (외부 contributor) |
| `intent` | ✅ | 3필드 객체 (아래) |
| `data_fingerprint` | ✅ | shape·통계 모먼트 (아래) |
| `config` | ✅ | 학습 설정 raw object (정밀, 비교용) |
| `metrics` | ✅ | 결과 metric (예: `{"AUC": 0.847, "runtime_sec": 180}`) |
| `worker_spec` | ✅ | CPU/GPU/RAM 등 하드웨어 사양 |
| `manifest` | ⚪ | 데이터·코드·모델 manifest 참조 (CQ가 생성) |
| `validation_report` | ⚪ | 자동 검증 결과 (선택) |
| `attribution` | ✅ | who/when/hash (아래) |
| `synthetic_source` | ✅* | tier=synthetic 시 필수 (아래) |

### intent (3필드)

```json
"intent": {
  "goal": "baseline_reproduction" | "sota_challenge" | "ablation"
        | "hyperparam_sweep" | "exploration",
  "expected_baseline": { "metric": "AUC", "value": 0.84 } | null,
  "tolerance": { "direction": "higher_is_better", "margin": 0.02 } | null
}
```

- null 허용 — contributor 부담 최소.
- null intent는 매치메이커 corpus에서 *weight 감쇠*.
- `actual_metric` 대 `expected_baseline ± tolerance` 비교가 "성공/실패"의
  spec-level 정의.

### data_fingerprint (PHI-safe by construction)

```json
"data_fingerprint": {
  "modality": "tabular" | "vision" | "nlp" | ...,
  "sample_count_band": "1k-10k" | "10k-100k" | "100k-1M" | ...,
  "schema": { ... },                    // tabular: 컬럼 dtype 등
  "statistical_moments": {              // 대역 표현 (PHI 차단)
    "class_balance": "5-15%",           // 정확값 X
    "missing_pct": "0-5%",
    "mean_band": { ... },               // 각 feature mean 대역
    "std_band": { ... }
  },
  "dtype_summary": { ... }
}
```

**자동 차단되는 값**:
- raw sample (이미지·텍스트·CSV row)
- 정확한 sample count (반드시 대역으로 quantize)
- 환자 ID, 이메일, 이름 등 식별자
- 정확한 metric distribution (mean/std는 대역만)

TC ingestion이 schema 검증 시 위 값이 발견되면 *deposit 거부 또는 자동 strip*.

### worker_spec

```json
"worker_spec": {
  "cpu_cores": 32,
  "ram_gb": 64,
  "gpu_model": "RTX 5080",
  "vram_gb": 16,
  "has_gpu": true
}
```

CPU/GPU 정보는 PHI 아님 — *어떤 하드웨어 환경에서 무엇이 작동했나*가 핵심.

### attribution

```json
"attribution": {
  "contributor_id": "user-abc" | null,   // anonymous OK v0.1 (CQ identity reference)
  "content_hash": "sha256:...",
  "created_at": "2026-05-13T07:30:00Z",
  "pcq_version": "2.0.0"
}
```

`content_hash`는 `(tier, intent, config, metrics, fingerprint, ...)`로부터 계산된
SHA256 — evidence immutability 검증.

### synthetic_source (tier=synthetic 시 필수)

```json
"synthetic_source": {
  "source_model": "gemini-1.5-flash" | "claude-sonnet" | "codex-...",
  "prompt_hash": "sha256:...",          // 재현용
  "generated_at": "2026-05-13T07:00:00Z",
  "verifier": "ev-real-xyz" | null      // ⚠ server-derived (아래)
}
```

- `verifier`는 **server-derived, read-only**. contributor가 ingest payload에 채워
  보내도 무시(silent strip). content_hash 계산에서도 제외되므로 검증에 영향 없음.
- SSOT는 `reciprocity_event` 테이블의 `promote`/`contradicts` 이벤트. `GET
  /evidence/{synthetic_id}` 응답 시 server가 event store에서 read-time JOIN해 채움.
- 이 정합이 **L1 immutable** 약속(`run_record` 변경 불가)을 보존한다.
- 채워졌을 때: 해당 real evidence가 synthetic prediction을 검증한 결과.
  일치하면 *promote*, 불일치하면 *contradicts*. 둘 다 valid event.

## TC ingestion의 적용 흐름

```
1. CQ → POST /ingest body
2. TC ingestion module:
   - JSON schema 검증
   - tier='synthetic'이면 synthetic_source 강제 (DB CHECK constraint와도 정합)
   - data_fingerprint 자동 정화 (raw sample/ID/정확 count 제거)
   - content_hash 계산 후 unique 검증
   - intent null이면 weight 감쇠 플래그
3. evidence 저장 (Library DB) + cluster_impact 계산 + retirement check 트리거
4. 응답: evidence_id + cluster_impact (promoted/contradicted synthetic IDs)
```

## 버전 정책

- **2.0.0**: TC v0.1 출시 시점의 minimum. intent/fingerprint/synthetic 필드 도입.
- **2.x**: backward compatible 추가 (예: 새 modality enum).
- **3.0.0**: breaking change 시 (예: schema 구조 재편). v0.2~0.3에서 검토.

## 관련 결정

- intent 3필드: `/Users/changmin/git/TheCommons/.cq/runtime/ideas/the-commons-vision.md` (#2)
- data fingerprint·PHI 차단: 같은 파일 (#6)
- synthetic tier·attribution·verifier: `the-commons-v0.1-design.md` (#6, #7)
- outreach origin: `the-commons-success-metrics.md` (#4)
- 자연어 직렬화는 TC 내부 처리: `the-commons-matchmaker-design.md` (#1) —
  pcq spec엔 *자연어 description 필드 없음*. 그건 TC Serializer가 만드는 derived view.

## 별 repo (cq_ml/pcq) 동기화

- 본 spec은 TC repo의 *참조 사본*. 정식 release는 cq_ml/pcq에서 진행.
- 두 repo의 spec이 어긋나면 *cq_ml/pcq를 source of truth*로 본다.
- TC ingestion module은 pcq 2.x JSON Schema 파일을 직접 fetch하거나 vendored 형태로
  사용 (plan 단계 결정).
