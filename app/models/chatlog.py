from sqlalchemy import Column, VARCHAR, Integer, DateTime, ForeignKey
from app.db import Base

class ChatLog(Base):
    __tablename__ = "chatlog"

    id         = Column(Integer,       primary_key=True, autoincrement=True)
    user_id    = Column(VARCHAR(50),   ForeignKey("login.id"), nullable=False)
    question   = Column(VARCHAR(1000), nullable=False)
    answer     = Column(VARCHAR(5000), nullable=True)
    status     = Column(VARCHAR(20),   nullable=False)
    error_code = Column(VARCHAR(50),   nullable=True)
    latency_ms = Column(Integer,       nullable=True)
    request_id = Column(VARCHAR(64),   nullable=False)
    model      = Column(VARCHAR(80),   nullable=True)
    created_at = Column(DateTime,      nullable=False)
