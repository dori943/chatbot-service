from fastapi                import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth      import login, register
from app.schemas.auth       import AuthRequest
from app.db                 import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login")
async def login_route(data: AuthRequest, db: AsyncSession = Depends(get_db)):
    return await login(data, db)

@router.post("/register")
async def register_route(data: AuthRequest, db: AsyncSession = Depends(get_db)):
    return await register(data, db)
