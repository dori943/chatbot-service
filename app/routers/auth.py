from fastapi       import APIRouter
from services.auth import login

router = APIRouter(prefix="/login", tags=["login"])

@router.post("/login")
def login_route():
    return login()