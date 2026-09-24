from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency  import run_in_threadpool

from app.models.login       import Login
from app.schemas.auth       import AuthRequest
from app.utils.security     import verify_password, hash_password, create_token

async def check_user(user_id: str, db: AsyncSession) -> bool:
    async with db.begin():
        return await db.get(Login, user_id) is not None

async def register(data: AuthRequest, db: AsyncSession):
    password = await run_in_threadpool(hash_password, data.pw)
    user = Login(id=data.id, pw=password)

    async with db.begin():
        db.add(user)

    return {"message": "register success"}

async def login(data: AuthRequest, db: AsyncSession):
    async with db.begin():
        user = await db.get(Login, data.id)

    if user is None or not await run_in_threadpool(verify_password, data.pw, user.pw):
        return {"message": "login failed"}

    token = create_token(user.id)

    return {
        "message"    : "login success",
        "token"      : token,
        "token_type" : "bearer"
    }
