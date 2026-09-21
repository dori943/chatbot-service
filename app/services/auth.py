from sqlalchemy.orm import Session
from app.models.login import Login
from app.schemas.auth import AuthRequest

def register(data: AuthRequest, db: Session):
    user = Login(id=data.id, pw=data.pw)

    db.add(user)
    db.commit()

    return {"message": "register success"}

def login(data: AuthRequest, db: Session):
    user = (
        db.query(Login)
        .filter(Login.id == data.id)
        .first()
    )

    if user is None or user.pw != data.pw:
        return {"message": "login failed"}

    return {"message": "login success"}
