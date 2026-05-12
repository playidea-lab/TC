"""JWT verify — 키 inject 방식으로 외부 파일 없이 단위 검증."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from the_commons.auth.jwt_verify import (
    JWTVerificationError,
    verify_jwt,
)
from the_commons.settings import settings


@pytest.fixture
def rsa_keypair() -> tuple[bytes, bytes]:
    """테스트용 RSA 키쌍 (PEM)."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _issue_token(
    private_pem: bytes,
    *,
    sub: str = "user-123",
    issuer: str | None = None,
    audience: str | None = None,
    expires_in: timedelta = timedelta(minutes=5),
) -> str:
    """테스트용 JWT 발행."""
    now = datetime.now(UTC)
    payload = {
        "iss": issuer or settings.cq_jwt_issuer,
        "aud": audience or settings.cq_jwt_audience,
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


def test_verify_jwt_with_valid_token_returns_claims(rsa_keypair: tuple[bytes, bytes]) -> None:
    """올바른 토큰은 VerifiedClaims로 디코딩."""
    private_pem, public_pem = rsa_keypair
    token = _issue_token(private_pem, sub="ev-contributor-1")

    claims = verify_jwt(token, public_key=public_pem)

    assert claims.contributor_id == "ev-contributor-1"
    assert claims.issuer == settings.cq_jwt_issuer
    assert claims.audience == settings.cq_jwt_audience


def test_verify_jwt_with_expired_token_raises(rsa_keypair: tuple[bytes, bytes]) -> None:
    """만료된 토큰은 검증 실패."""
    private_pem, public_pem = rsa_keypair
    token = _issue_token(private_pem, expires_in=timedelta(seconds=-10))

    with pytest.raises(JWTVerificationError):
        verify_jwt(token, public_key=public_pem)


def test_verify_jwt_with_wrong_issuer_raises(rsa_keypair: tuple[bytes, bytes]) -> None:
    """issuer 불일치는 거부."""
    private_pem, public_pem = rsa_keypair
    token = _issue_token(private_pem, issuer="malicious.example.com")

    with pytest.raises(JWTVerificationError):
        verify_jwt(token, public_key=public_pem)


def test_verify_jwt_with_wrong_audience_raises(rsa_keypair: tuple[bytes, bytes]) -> None:
    """audience 불일치는 거부."""
    private_pem, public_pem = rsa_keypair
    token = _issue_token(private_pem, audience="other-service")

    with pytest.raises(JWTVerificationError):
        verify_jwt(token, public_key=public_pem)


def test_verify_jwt_with_tampered_token_raises(rsa_keypair: tuple[bytes, bytes]) -> None:
    """다른 키로 서명된 토큰은 거부."""
    _, public_pem = rsa_keypair
    other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    forged = _issue_token(other_pem)

    with pytest.raises(JWTVerificationError):
        verify_jwt(forged, public_key=public_pem)


def test_verify_jwt_without_sub_claim_raises(rsa_keypair: tuple[bytes, bytes]) -> None:
    """sub claim 없으면 require 검증에서 실패."""
    private_pem, public_pem = rsa_keypair
    now = datetime.now(UTC)
    payload = {
        "iss": settings.cq_jwt_issuer,
        "aud": settings.cq_jwt_audience,
        # sub 누락
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    with pytest.raises(JWTVerificationError):
        verify_jwt(token, public_key=public_pem)
