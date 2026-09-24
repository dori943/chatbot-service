from sqlalchemy.exc         import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency  import run_in_threadpool

from app.core.errors        import APIError, ErrorCode
from app.core.logging       import log_event
from app.models.login       import Login
from app.schemas.auth       import AuthRequest
from app.utils.security     import verify_password, hash_password, create_token
from app.utils              import security

async def check_user(user_id: str, db: AsyncSession) -> bool:
    try:
        user = await db.get(Login, user_id)
        await db.commit()
        return user is not None
    except SQLAlchemyError as exc:
        log_event("auth_user_lookup_failed", exc=exc)
        await db.rollback()
        raise


def validate_auth(data: AuthRequest):
    if not data.id.strip():
        raise APIError(422, ErrorCode.INVALID_INPUT, "아이디를 입력해 주세요.")
    if len(data.id) > 50:
        raise APIError(422, ErrorCode.INVALID_INPUT, "아이디는 50자 이내로 입력해 주세요.")
    if not data.pw.strip():
        raise APIError(422, ErrorCode.INVALID_INPUT, "비밀번호를 입력해 주세요.")
    if len(data.pw.encode("utf-8")) > 72:
        raise APIError(422, ErrorCode.INVALID_INPUT, "비밀번호는 UTF-8 기준 72바이트 이내로 입력해 주세요.")


async def register(data: AuthRequest, db: AsyncSession):
    validate_auth(data)
    password = await run_in_threadpool(hash_password, data.pw)
    user = Login(id=data.id, pw=password)

    try:
        db.add(user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        error_args = getattr(exc.orig, "args", ())
        if error_args and error_args[0] == 1062:
            raise APIError(409, ErrorCode.USER_EXISTS, "이미 사용 중인 아이디입니다.") from None
        log_event("auth_register_failed", exc=exc)
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "회원가입을 완료하지 못했습니다.") from None
    except SQLAlchemyError as exc:
        log_event("auth_register_failed", exc=exc)
        await db.rollback()
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "회원가입을 완료하지 못했습니다.") from None

    log_event("auth_register_success")
    return {"message": "register success"}

async def login(data: AuthRequest, db: AsyncSession):
    validate_auth(data)
    if not security.KEY:
        raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 서비스를 사용할 수 없습니다.")

    try:
        user = await db.get(Login, data.id)
        await db.commit()
    except SQLAlchemyError as exc:
        log_event("auth_login_lookup_failed", exc=exc)
        await db.rollback()
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "로그인 정보를 확인하지 못했습니다.") from None

    try:
        valid = user is not None and await run_in_threadpool(verify_password, data.pw, user.pw)
    except ValueError as exc:
        log_event("auth_password_verify_failed", exc=exc)
        raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 정보를 확인하지 못했습니다.") from None
    if not valid:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "아이디 또는 비밀번호를 확인해 주세요.")

    token = create_token(user.id)
    log_event("auth_login_success")

    return {
        "message"    : "login success",
        "token"      : token,
        "token_type" : "bearer"
    }
