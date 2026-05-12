"""FastAPI 의존성 함수 — endpoint에서 `Depends(require_contributor)` 형태로 사용."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from the_commons.auth.jwt_verify import (
    JWTConfigError,
    JWTVerificationError,
    VerifiedClaims,
    verify_jwt,
)

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_contributor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> VerifiedClaims:
    """Authorization: Bearer <jwt> 헤더를 검증해 VerifiedClaims 반환.

    검증 실패는 401, 서버 설정 오류는 500.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer 토큰 필요",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_jwt(credentials.credentials)
    except JWTVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except JWTConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"JWT 설정 오류: {exc}",
        ) from exc
