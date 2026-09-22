from fastapi            import APIRouter, Depends
from sqlalchemy.orm     import Session
from app.services.auth  import login, register
from app.schemas.auth   import AuthRequest
from app.db             import get_db

router = APIRouter(prefix="/login", tags=["login"])

@router.post("/login")
def login_route(data: AuthRequest, db: Session = Depends(get_db)):
    return login(data, db)

@router.post("/register")
def login_route(data: AuthRequest, db: Session = Depends(get_db)):
    return register(data, db)