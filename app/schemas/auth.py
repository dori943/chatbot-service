from pydantic import BaseModel

class AuthRequest(BaseModel):
    id: str
    pw: str