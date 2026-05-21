"""환경변수 기반 설정. Pydantic Settings로 .env 파일 자동 로드."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """전역 설정. .env 또는 환경변수에서 로드.

    하드코딩 금지 — 모든 URL/경로/임계값은 여기로.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 데이터베이스
    database_url: str = Field(
        default="postgresql://commons:changeme@localhost:5432/commons",
        description="PostgreSQL (pgvector extension 필수)",
    )

    # Gemini
    google_api_key: str = Field(default="", description="Google Generative AI API key")
    gemini_embedding_model: str = Field(default="gemini-embedding-2")
    gemini_reranker_model: str = Field(default="gemini-2.5-flash")

    # OpenAI — generation(synthesizer + infogain prior)용. Gemini quota 회피.
    # embedding은 차원 호환 위해 Gemini 유지 (전환 시 corpus 전체 re-embed 필요).
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini")

    # CQ JWT
    cq_jwt_public_key_path: str = Field(default="", description="CQ가 발행한 JWT 검증용 공개키")
    cq_jwt_issuer: str = Field(default="cq.pilab.kr")
    cq_jwt_audience: str = Field(default="the-commons")

    # Retirement
    retirement_real_threshold: int = Field(
        default=3,
        description="cluster당 real evidence 누적이 이 임계값 도달 시 synthetic을 deprecated 처리",
    )
    retirement_check_interval_sec: int = Field(default=300)

    # Serializer
    template_version: str = Field(default="v1")

    # 매치메이커
    retrieve_top_k: int = Field(default=20, description="Stage 1 vector retrieve 상위 K개")
    recommend_top_n: int = Field(default=5, description="Stage 2 rerank 후 응답 상위 N개")

    # ε-novelty mix 정책 (cq-tc-autonomous-experiment-loop v1)
    exploration_policy: Literal["fixed"] = Field(
        default="fixed",
        description="v1엔 fixed만. v2부터 corpus_decay/stagnation 등.",
    )
    exploration_epsilon: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="ε-novelty mix의 explore 분기 확률. 1-ε는 exploit (infogain→within-recipe LLM).",
    )

    # 로깅
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json", description="json | console")

    # 프록시 — production에서 K8s Ingress 뒤면 True. dev/single-pod는 False.
    trust_forwarded_for: bool = Field(
        default=False,
        description=(
            "True면 X-Forwarded-For 헤더의 첫 IP를 client로 신뢰. "
            "trusted proxy(K8s Ingress 등) 뒤에서만 True로 설정. "
            "False면 spoofing 위험으로 사용 안 함."
        ),
    )

    # Gemini cost ceiling — 일일 한도. 0 = 무제한 (default).
    # 한도 도달 시 /ingest /recommend가 503 (Gemini abuse 방어 외 *우리 측 bug*도 cap).
    gemini_daily_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Gemini 호출 일일 USD 예산. 도달 시 endpoint 503 반환. "
            "0이면 ceiling 미적용 (dev). production은 monthly_budget/30 권장."
        ),
    )

    # HTTP request body size limit (DoS·malformed body 방어).
    # pcq evidence record는 보통 5~10KB, fingerprint·metrics 풍부해도 ~100KB.
    # 1MB는 큰 안전망.
    max_request_body_bytes: int = Field(
        default=1_048_576,  # 1 MB
        ge=1024,
        description=(
            "Content-Length가 이 한도 초과 시 413. "
            "DoS·malformed body 방어용. 단위: bytes."
        ),
    )

    # 서비스화 게이트 임계 — 전부 sentinel 기본 (숫자 발명 금지, 출시 후
    # 데이터로 보정). 미설정이면 해당 조건은 "측정 불가" → 거짓 통과 금지.
    productization_promote_rate_floor: float = Field(
        default=-1.0,
        description="재현 promote-rate 바닥. -1.0=미설정 → C3 측정 불가.",
    )
    productization_min_reproductions: int = Field(
        default=0,
        ge=0,
        description=(
            "C3 산정 최소 재현(promote+contradicts) 건수. "
            "0 또는 미달이면 C3 측정 불가 (small-N 거짓 통과 방어)."
        ),
    )
    productization_gate_escape_windows: int = Field(
        default=0,
        ge=0,
        description=(
            "연속 미트립 verdict window가 이 수 이상이면 강제 재결정 요구. "
            "0이면 강제 재결정 비활성."
        ),
    )


settings = Settings()
