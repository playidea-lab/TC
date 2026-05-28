# explore-loop v3 — 에이전트를 인-루프 변이연산자로, cq_dispatch v2 전면 재설계

> autoresearch의 본질(AI가 코드를 자기수정)을 헤드리스 자율 루프로 흡수한다. 운전자=Claude Code+`/loop`, 컨트롤러=MCP 서비스(정책 엔진+메모리), 변이=에이전트(3-E: exploit/explore/explosion), 디스패치=cq_dispatch v2(Worker 추상, 원격+로그 환류). mvtec은 v3로 강제 마이그레이션.

## 왜 이 아이디어인가

[[explore-loop-autoresearch-profile]] 구현(2026-05-27)이 잡은 결론: autoresearch를 *흡수했다*고 보기 어렵다 — **config 스윕 그림자**만 흡수했다. autoresearch의 영혼인 "AI가 코드를 손대고, traceback 보고 자기수정한다"가 헤드리스 루프 밖에 머물렀다(수동 SKILL.md 경로). 우리 explore-loop 정체성 *"AlphaEvolve-lite: 에이전트=변이연산자"*가 *루프에 배선되지 않은* 채로 남았다.

v3는 그 배선을 끝낸다. **Claude Code 자체를 자율 루프의 운전자**로 만들고(/loop으로 무인 반복), **컨트롤러를 MCP 도구**로 강등(정책+메모리만), **3-E 모드**(exploit=숫자, explore=구조, explosion=웹)로 변이를 명시적으로 분류, **cq_dispatch v2**로 워커 토폴로지를 추상화하고 stderr/traceback을 1급 시민으로 만들어 *에이전트의 자기수정*을 가능하게 한다.

리빌딩 결단의 근거: v2의 cq_dispatch는 "로컬 워크스페이스 + pcq 자체완결 스크립트 + describe 로컬 읽기"가 골격에 박혔는데 — ② 본질은 *세 가정 모두* 위배한다. 패치 경로(현재 hook 2개에서 5~6개로 누적)는 한 달 뒤 spaghetti 보장. 전면 재설계가 *시간상 빠르진 않지만 결과 품질·미래 비용*에서 정답.

## 풀고자 하는 문제

**문제 1 — 본질 미흡수**: autoresearch의 자율 코드 진화는 *수동 에이전트* 경로에만 살아있고, 헤드리스 explore-loop은 숫자 스윕만 자동화한다. "밤새 자율로 코드를 연다"는 가설이 시스템에 없다.

**문제 2 — 원격 디스패치 미구현**: cq_dispatch가 "워커=로컬 노트북" 전제로 지어졌고, 원격 GPU 워커에서 describe.json·stderr·workspace 파일 회수 경로가 없다(검증된 mvtec도 모두 로컬 Mac이었다). autoresearch 워커는 원격 GPU(4090/3090)라 *현재 코드로는 0이 돈다*.

**문제 3 — 에이전트가 traceback을 못 본다**: ②의 본질("스택트레이스 읽고 고친다")인데 stderr 환류 경로가 없다. 자기수정 불가.

**문제 4 — 평가 무결성**: 자율 에이전트가 짠 코드가 evaluate_bpb를 monkeypatch하거나 val셋 훔치면 fitness 신호 corrupt. 자동화될수록 위험.

대상 사용자: **밤샘 자율 ML 연구 운영자**(=본인). CUDA(autoresearch nanochat)·MPS(mvtec) 양쪽.

## 기존 대안과 차이

| 대안 | 한계 | v3 차이 |
|---|---|---|
| autoresearch 원본 (Karpathy) | hill-climb, README가 "급진적 시도해줘"라 *빈다*(수동 다양성) | 컨트롤러 MCP가 "이 빈 셀 채워"라 *명령*(QD 다양성 강제) |
| explore-loop v2 + autoresearch profile (어제) | 헤드리스가 *숫자 스윕만* 자동화, 코드 진화는 수동 | Claude Code+/loop이 코드 진화도 헤드리스로 |
| 단순 Claude Code /loop autoresearch | archive 없음 → hill-climb로 회귀 | MCP 컨트롤러가 archive·정책·stagnation 감지 보유 |
| LLMatic (NAS via LLM+QD) | 일반 NAS, autoresearch 고정-compute 프로토콜·MCP 도구화 없음 | Claude Code 도구 생태계 + MCP + 원격 워커 통합 |
| 별도 헤드리스 에이전트 스크립트 (Option 2-B) | Claude Code 도구 생태계 재구현 필요(큰 빌드) | Claude Code 자체를 운전자로 — 파일/검색/실행 도구 재사용 |

## 요구사항 (EARS)

> 엔진 요구사항 [[explore-loop-qd-rigor]] RE1~RE11, autoresearch profile [[explore-loop-autoresearch-profile]] AR1~AR10을 **계승하되 V9·V14에서 부분 폐기**.

### 아키텍처
- **V1** 시스템은 항상 자율 루프 운전을 **Claude Code + `/loop`**에 위임한다. 결정론 Python 루프(`run_explore.py`)는 폐기한다.
- **V2** 시스템은 항상 컨트롤러를 **MCP 도구 서버**로 노출한다. 도구: `recommend_action(profile)`, `report_result(action, code, eval)`, `archive_state(filter)`, `build_explosion_query(stagnation_ctx)`. 정책 엔진(3-E 비율·stagnation 감지)이 도구 안에 산다.
- **V3** WHEN 에이전트(Claude Code) 라운드가 시작되면 THEN per-round SKILL이 다음 절차를 수행한다: `recommend_action` 호출 → 모드 분기(V6) → 코드 저술/치환 → cq_dispatch v2로 평가 → `report_result`.
- **V4** 시스템은 항상 **cq_dispatch v2**(Worker 추상)를 통해 디스패치한다. `Worker` 인터페이스(`upload`/`run`/`poll`/`download`/`tail_stderr`)의 두 구현 `LocalWorker`(현 mvtec 동작) + `CqRemoteWorker`(원격 GPU, NATS+`cq download`). dispatch 코어 흐름은 워커 종류를 모른다.
- **V5** 시스템은 항상 `JobSpec`(code·aux_files·command·monitor·metric_keys·timeout) → `JobResult`(fitness·metrics·describe·**stderr_tail**·success·workspace_id) 시그니처로 디스패치한다. **`stderr_tail`은 1급 시민** — 에이전트 자기수정의 입력.

### 3-E 모드
- **V6** 시스템은 항상 변이를 3개 모드로 분류한다: `exploit`(컨트롤러가 한 축 한 단계 키우는 결정론 치환, 거의 LLM 비용 없음), `explore`(에이전트가 부모 코드+타깃 셀 힌트로 구조 변형 저술), `explosion`(웹 검색 SOTA 통합).
- **V7** `explosion`은 **stagnation 트리거 전용**(최근 N 라운드 fitness/coverage 정체)이고 일반 모드 메뉴에 평등하게 들어가지 않는다. 별도 비용 cap 적용(V10).

### 봉인 (평가 무결성)
- **V8** WHEN 에이전트 변이 코드가 디스패치되기 전 THEN 정적 검사로 다음을 거부한다: `prepare` import의 monkeypatch 패턴, `evaluate_bpb` 재정의/우회, `@score` 직접 print(어댑터만 emit), val 데이터 경로 직접 read. 거부 시 라운드 실패 evidence로 적재(소비 비용 없이).

### 재현성·attribution
- **V9** (RE9 **부분 폐기**) per-run trajectory 재현성은 *상실*된다(에이전트 출력이 trajectory를 갈라놓으므로). 보존되는 것: 같은 (parent_genotype, prompt, agent_output) 입력에서 컨트롤러 결정·placement는 결정론. **모든 에이전트 출력에 attribution**(round_id·prompt·output·web_sources 기록).

### 비용·자율성·관측성
- **V10** 시스템은 항상 비용 cap을 강제한다: per-round LLM 토큰 cap, 총 run LLM 예산 cap, `explosion` 별도 cap, GPU 라운드 cap. cap 도달 시 자율 정지.
- **V11** IF 디스패치가 실패하고 stderr_tail이 있으면 THEN 에이전트는 같은 라운드 안에서 **1회 자기수정**을 시도한다(예산 잔여 시). 반복 실패는 placement skip + evidence 적재.
- **V12** 시스템은 항상 매 라운드를 영속한다: `{round_id, mode, parent_genotype, target_cell, prompt, agent_output, eval_result, placement, attribution}`. 비결정 루프 forensic 디버그용.

### 자율성 운영
- **V13** WHEN v3가 활성화되면 THEN `settings.json`에 라운드 행동(cq 도구·MCP·WebSearch·파일 쓰기·`uv run`)을 **사전 허용**한다 — 권한 프롬프트로 자율이 깨지지 않게.

### 마이그레이션
- **V14** mvtec profile은 v3로 **강제 마이그레이션**된다(Claude Code+/loop+MCP+cq_dispatch v2). 병행 경로 없음. `run_explore.py` 폐기, 기존 mvtec state는 v3 archive로 마이그레이션 또는 무시(첫 v3 run = cold start).

## 범위 외
- 결정론 Python 헤드리스 루프(run_explore.py) — 폐기, 재사용 안 함.
- coverage-driven *사전* binning을 통한 빈 셀 *겨냥* — 에이전트 변이는 셀을 신뢰성 있게 못 겨냥하므로 **post-hoc placement**로 이동. *부수 효과: BD 축이 실행 후 측정치(num_params·tokens·mfu·vram)로 자유로워짐 — Option A 부활*. AR3가 이에 맞춰 다시 갱신될 가능성.
- (다) 점진 strangler 패턴 — 회귀 위험은 낮지만 깨끗함이 부족. v3는 (나) 전면 재설계 선택.
- 별도 headless 에이전트 스크립트(Option 2-B) — Claude Code 도구 재구현 부담으로 미채택.
- ①(numeric 상수 surface 확장 단독) — 에이전트가 어차피 같은 일 함. `exploit` 모드 안에 흡수됨.

## 리스크

| 리스크 | 심각도 | 초기 대응 |
|---|---|---|
| R1 cq_dispatch v2 일정 슬립(5~8일 추정 vs 실제) + mvtec 회귀 부담 | 🔴 | W1 단독 집중. mvtec smoke를 v3 첫 검증 게이트로(autoresearch 전에) |
| R2 `/loop` 100+ 라운드 밤샘 자율 미검증 | 🔴 | W3 단계 *짧은 cycle*(5~10 라운드)부터. 실패 시 (Option 2-B) headless 스크립트로 후퇴 |
| R3 권한 프롬프트가 자율 깨뜨림 | 🟠 | /fewer-permission-prompts로 settings.json 사전 허용 (V13) |
| R4 토큰 비용 $100~200/밤샘 + prompt caching 의존 | 🟠 | V10 cap 엄격. 첫 run은 짧게(예산 $30). 모드별 비용 측정 |
| R5 봉인 미흡 → fitness reward-hacking | 🔴 | V8 정적 검사를 *디스패치 전 게이트*로 강제. 차단 시 0비용 fail |
| R6 SKILL.md 강제력 약하면 에이전트가 추천 무시 → hill-climb 회귀 | 🟠 | "비협상" 톤 + 추천 거부 시 round abort 정책 |
| R7 v2 RE9(재현성) 약화 수용 — v2 자기-원칙 위반 | 🟡 | V9에 명시. attribution이 보상 |
| R8 Explosion 비용 폭주 | 🟡 | V7 stagnation gate + V10 별도 cap |
| R9 첫 run에서 "잘 도는지" 판단 기준 모호 | 🟡 | V12 영속 + 사전 정의된 success/kill criterion |

## 탐구 중 발견한 인사이트

- **②-only가 부수적으로 Option A를 부활시킨다.** coverage-driven 사전 binning이 무너지면 post-hoc placement로 가게 되고, BD 축을 측정 phenotype(num_params·tokens·mfu·vram)으로 자유롭게 쓸 수 있다 — 어제 Option C로 후퇴한 "literal Chinchilla 지도"가 v3에서 재가능. 단점: 빈 셀 *겨냥* 능력 상실, coverage가 운에 맡겨짐.
- **컨트롤러 "강등"은 사실 *역할 재정의*다, 약화가 아니다.** 단순 archive CRUD가 아니라 정책 엔진(3-E 비율·stagnation→Explosion 트리거)+ 메모리 서비스라는 *핵심 영혼*은 살아있다. 도구 형태일 뿐.
- **cq_dispatch v2의 진짜 가치는 "원격" 자체가 아니라 `stderr_tail`이다.** ②의 본질은 에이전트가 traceback 읽고 자기수정 — 이 환류 경로가 인터페이스에 박혀야(`JobResult.stderr_tail`) 안 까먹는다.
- **"리빌딩이 더 빠르다"는 환상이다.** 같거나 약간 느림. 정당화는 *결과 품질 + 미래 비용*에서, *raw 시간*에서가 아님. (나) 선택은 그 trade를 받아들인 결정.
- **③의 Explosion이 가장 외주 비싼 단일 행동이라 stagnation-gate가 필수**. 일반 모드 메뉴에 평등하게 두면 폭주.

## 계획 (3 phase + 후속)

- **W1 — cq_dispatch v2** (가장 큰 미지수, 가장 위험). Worker 추상(LocalWorker + CqRemoteWorker) + JobSpec/JobResult + `stderr_tail` 1급. **mvtec smoke(LocalWorker로)가 W1 끝 게이트**(v3 첫 검증). 회귀 통과해야 W2.
- **W2 — controller MCP + 봉인** + per-round SKILL.md. map_elites 자료구조 재사용, MCP 도구 4개. V8 정적 검사 모듈. SKILL.md *비협상* 톤.
- **W3 — Claude Code /loop 통합 + 짧은 smoke** (5~10 라운드, autoresearch 원격 4090/3090). V10 cap 엄격, V12 영속. 통과 시 본격 밤샘.
- **W4+ — 보강** : 3-E 정책 튜닝, Explosion 서브시스템(쿼리 합성), 비용 측정, kill/success criterion 정량화, mvtec v3 마이그레이션.

선결 (사용자/외부):
- **GPU 워커 온라인 복구** (4090 또는 3090 머신에서 `cq worker start`). v3 W3 smoke의 전제.
- **워커에 cu128 환경 + ~/.cache/autoresearch 데이터 준비** (autoresearch P-setup).

## 참고

- 직전 흡수: [[explore-loop-autoresearch-profile]] (config 스윕만 흡수, 본질 미흡수 — 이 idea가 그 분석에서 출발).
- 엔진 idea: [[explore-loop-qd-rigor]] (RE1~11 계승, RE9 V9에서 부분 폐기).
- v1: [[cq-tc-agentic-exploration-loop]] (강제 탐색 skill 원형).
- 외부: AlphaEvolve(arXiv 2506.13131) — 에이전트=변이연산자 정합. LLMatic(arXiv 2306.01102) — LLM+QD NAS 메커니즘 검증. Karpathy autoresearch(github.com/karpathy/autoresearch).
- 기존 자산 처분: `run_explore.py` 폐기. `map_elites.py` 자료구조 재사용. `profile_mvtec_ad.py`/`profile_autoresearch_nanochat.py` 일부 재사용(materialize는 exploit 모드에서). 어제 머지된 PR(cq-ops !3, TC #1)은 vendoring·profile·idea 보존, cq_dispatch는 v2가 대체.

---
*Generated by /pi on 2026-05-28 — [[explore-loop-autoresearch-profile]] 구현 후 본질 미흡수 자기진단으로부터.*
