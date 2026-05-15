"""환경변수 기반 설정. Pydantic Settings로 .env 파일 자동 로드."""

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


settings = Settings()
