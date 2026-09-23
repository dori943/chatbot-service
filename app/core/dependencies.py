import jwt

from fastapi          import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.utils        import security
from app.core.errors  import APIError

bearer = HTTPBearer(auto_error=False)
failed = APIError(401, "UNAUTHORIZED", "로그인이 필요합니다. 다시 로그인해 주세요.")

def get_token_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    if credentials is None: raise failed

    try:
        claims = jwt.decode(
            credentials.credentials,
            security.KEY,
            algorithms=[security.ALGORITHM],
            options={"require": ["id", "exp"]},
        )
    except jwt.InvalidTokenError: raise failed
    return claims["id"]