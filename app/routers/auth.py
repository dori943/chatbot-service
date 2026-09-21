from fastapi        import APIRouter, Depends
from sqlalchemy.orm import Session
from services.auth  import login, register
from schemas.auth   import AuthRequest
from db             import get_db

router = APIRouter(prefix="/login", tags=["login"])

@router.post("/login")
def login_route(data: AuthRequest, db: Session = Depends(get_db)):
    return login(data, db)

@router.post("/register")
def login_route(data: AuthRequest, db: Session = Depends(get_db)):
    return register(data, db)