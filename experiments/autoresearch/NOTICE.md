# autoresearch — vendored (무수정)

이 디렉토리의 `train.py`·`prepare.py`·`pyproject.toml`은 카파시 autoresearch에서
**한 줄도 고치지 않고** 복사한 것이다(explore-loop QD 엔진의 seed/evaluator로 사용).

- 출처: https://github.com/karpathy/autoresearch
- upstream commit: `228791fb499afffb54b46200aca536f79142f117`
- vendored: 2026-05-27
- 라이선스: MIT (upstream)

## 역할 (explore-loop profile `autoresearch-nanochat`)
- `prepare.py` — **고정 evaluator**(`evaluate_bpb` = ground truth). 수정 금지.
- `train.py` — **seed genotype**. 변이는 원본을 고치지 않고, `cq-ops`의
  `profile_autoresearch_nanochat.materialize()`가 상수(`DEPTH`/`ASPECT_RATIO` 등)를
  치환한 *변형 코드 문자열*을 생성해 디스패치한다. 이 파일 자체는 템플릿이며 불변.

## upstream 갱신 방법
`git clone`으로 받아 동일 SHA 대비 diff 확인 후 교체. 로컬 수정 금지(diff는 항상 0이어야 함).
