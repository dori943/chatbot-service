import logging

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import APIError
from app.db import SessionLocal
from app.models.login import Login
from app.utils import security

bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """기존 로그인 토큰의 서명·만료·사용자 존재 여부를 검증한다."""
    unauthorized = APIError(401, "UNAUTHORIZED", "로그인이 필요합니다. 다시 로그인해 주세요.")
    if credentials is None:
        raise unauthorized
    if not security.KEY:
        raise APIError(503, "AUTH_UNAVAILABLE", "인증 서비스를 사용할 수 없습니다.")
    try:
        claims = jwt.decode(
            credentials.credentials, security.KEY, algorithms=[security.ALGORITHM],
            options={"require": ["id", "exp"]},
        )
    except jwt.InvalidTokenError:
        raise unauthorized from None
    user_id = claims["id"]
    if not isinstance(user_id, str) or not user_id or len(user_id) > 50:
        raise unauthorized
    try:
        # AI를 기다리는 동안 DB 연결을 점유하지 않도록 여기서 세션을 닫는다.
        with SessionLocal() as db:
            if db.get(Login, user_id) is None:
                raise unauthorized
    except SQLAlchemyError:
        logger.error("auth_database_unavailable")
        raise APIError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없습니다.") from None
    return user_id
