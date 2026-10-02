from sqlalchemy import Column, VARCHAR
from app.db     import Base

class Login(Base):
    __tablename__ = "login"

    id = Column(VARCHAR(50),  primary_key=True)
    pw = Column(VARCHAR(255), nullable=False)
