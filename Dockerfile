# syntax=docker/dockerfile:1.7
# Multi-stage: builder는 uv로 의존성·앱 빌드, runtime은 slim
# 빌드: docker build -t the-commons:v0.1 .
# 실행: docker run --env-file .env -p 8000:8000 the-commons:v0.1

ARG PYTHON_VERSION=3.12-slim

# ============================================================================
# Builder
# ============================================================================
FROM python:${PYTHON_VERSION} AS builder

# uv binary 복사 (lock 기반 reproducible install)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# 의존성 lock 먼저 — layer caching
COPY pyproject.toml uv.lock README.md ./

# uv는 src/the_commons가 있어야 build (hatchling이 패키지 인식)
COPY src/ ./src/

# --frozen: uv.lock 그대로 사용 (CI reproducibility)
# --no-dev: 개발 의존성(pytest/ruff/mypy) 제외
RUN uv sync --frozen --no-dev

# ============================================================================
# Runtime
# ============================================================================
FROM python:${PYTHON_VERSION} AS runtime

# psycopg binary는 libpq 의존 (이미 binary 패키지에 포함). 단 일부 환경에서
# tzdata 필요할 수 있어 minimal로만 추가.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 비루트 사용자 — security 기본
RUN groupadd --system commons && useradd --system --gid commons commons

COPY --from=builder --chown=commons:commons /app/.venv ./.venv
COPY --from=builder --chown=commons:commons /app/src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

USER commons

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
        sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)" \
        || exit 1

# uvloop는 docker-compatible. worker 1개 — K8s에서 replica로 scale.
CMD ["uvicorn", "the_commons.main:app", "--host", "0.0.0.0", "--port", "8000"]
