"""CQ JWT 검증.

CQ frontline이 발행한 JWT를 TC가 공개키로 검증한다. signature, issuer,
audience, expiration을 모두 확인. 검증 실패는 호출자에게 명시 예외로 전파.

Phase 1엔 internal traffic이므로 별도 OAuth provider 없이 CQ 공개키 한 곳만
신뢰한다. Phase 3에서 분사 시 자체 발행으로 전환 가능.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt

from the_commons.settings import settings

logger = logging.getLogger(__name__)


class JWTConfigError(RuntimeError):
    """JWT 검증 설정 오류 — 공개키 미설정 등."""


class JWTVerificationError(RuntimeError):
    """JWT 검증 실패 — 서명/만료/issuer/audience 불일치."""


@dataclass(frozen=True)
class VerifiedClaims:
    """검증 통과한 JWT의 핵심 claim.

    contributor_id는 CQ가 식별한 사용자 ID (TC는 *reference*만 보유).
    """

    contributor_id: str
    issuer: str
    audience: str
    raw_claims: dict[str, Any]


def _load_public_key(path: str) -> bytes:
    """파일에서 공개키 로딩. 경로 미설정·파일 없음은 JWTConfigError."""
    if not path:
        raise JWTConfigError("CQ_JWT_PUBLIC_KEY_PATH 미설정")
    key_path = Path(path)
    if not key_path.is_file():
        raise JWTConfigError(f"JWT 공개키 파일 없음: {path}")
    return key_path.read_bytes()


def verify_jwt(token: str, *, public_key: bytes | None = None) -> VerifiedClaims:
    """JWT 검증 → VerifiedClaims 반환.

    Args:
        token: Bearer 헤더에서 추출한 raw JWT string
        public_key: 테스트에서 inject 가능. None이면 settings 경로에서 로딩.

    Raises:
        JWTConfigError: 공개키 설정 문제
        JWTVerificationError: 서명·issuer·audience·만료 검증 실패
    """
    if public_key is None:
        public_key = _load_public_key(settings.cq_jwt_public_key_path)

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            issuer=settings.cq_jwt_issuer,
            audience=settings.cq_jwt_audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.InvalidTokenError as exc:
        raise JWTVerificationError(f"JWT 검증 실패: {exc}") from exc

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise JWTVerificationError("JWT subject(sub) claim 누락 또는 비문자열")

    return VerifiedClaims(
        contributor_id=sub,
        issuer=str(claims.get("iss", "")),
        audience=str(claims.get("aud", "")),
        raw_claims=claims,
    )
