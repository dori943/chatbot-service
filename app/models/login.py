from sqlalchemy import Column, String
from app.db     import Base

class Login(Base):
    __tablename__ = "login"

    id = Column(String(50),  primary_key=True)
    pw = Column(String(255), nullable=False)
