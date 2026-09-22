import bcrypt
import jwt

from datetime import datetime, timedelta, timezone
from os       import getenv

KEY       = getenv("SECRET_KEY")
ALGORITHM = "HS256"
TOKEN_EXP = 60

def hash_password(password: str):
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

def verify_password(password: str, hashed_password: str):
    return bcrypt.checkpw(
        password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )

def create_token(user_id: str):
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXP)

    payload = {
        "id" : user_id,
        "exp": exp
    }

    return jwt.encode(payload, KEY, algorithm=ALGORITHM)