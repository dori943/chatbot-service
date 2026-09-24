import jwt

from fastapi                import Depends
from fastapi.security       import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc         import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors        import APIError
from app.db                 import get_db
from app.services           import auth
from app.utils              import security

bearer = HTTPBearer(auto_error=False)

async def get_token_id(
    credentials : HTTPAuthorizationCredentials | None = Depends(bearer),
    db          : AsyncSession                        = Depends(get_db),
) -> str:
    failed = APIError(401, "UNAUTHORIZED", "로그인이 필요합니다. 다시 로그인해 주세요.")
    if credentials is None: raise failed
    if not security.KEY:
        raise APIError(503, "AUTH_UNAVAILABLE", "인증 서비스를 사용할 수 없습니다.")

    try:
        claims = jwt.decode(
            credentials.credentials,
            security.KEY,
            algorithms = [security.ALGORITHM],
            options    = {"require": ["id", "exp"]},
        )
    except jwt.InvalidTokenError: raise failed from None

    user_id = claims["id"]
    if not isinstance(user_id, str) or not user_id or len(user_id) > 50:
        raise failed

    try:
        exists = await auth.check_user(user_id, db)
    except SQLAlchemyError:
        raise APIError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없습니다.") from None
    if not exists:
        raise failed

    return user_id
