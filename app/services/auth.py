from sqlalchemy.orm     import Session
from app.models.login   import Login
from app.schemas.auth   import AuthRequest
from app.utils.security import verify_password, hash_password, create_token

def register(data: AuthRequest, db: Session):
    user = Login(id=data.id, pw=hash_password(data.pw))

    db.add(user)
    db.commit()

    return {"message": "register success"}

def login(data: AuthRequest, db: Session):
    user = (
        db.query(Login)
        .filter(Login.id == data.id)
        .first()
    )

    if user is None or not verify_password(data.pw, user.pw):
        return {"message": "login failed"}

    token = create_token(user.id)

    return {
        "message"    : "login success",
        "token"      : token,
        "token_type" : "bearer"
    }