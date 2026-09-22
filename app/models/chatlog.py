from sqlalchemy import BigInteger, Column, VARCHAR, Integer, ForeignKey
from sqlalchemy.dialects.mysql import DATETIME
from app.db import Base

class ChatLog(Base):
    __tablename__ = "chat_logs"

    id         = Column(BigInteger(),  primary_key=True      , autoincrement=True)
    user_id    = Column(VARCHAR(50),   ForeignKey("login.id"), nullable=False)
    question   = Column(VARCHAR(5000), nullable=False)
    answer     = Column(VARCHAR(5000), nullable=True)
    status     = Column(VARCHAR(20),   nullable=False)
    error_code = Column(VARCHAR(50),   nullable=True)
    latency_ms = Column(Integer,       nullable=True)
    request_id = Column(VARCHAR(64),   nullable=False)
    model      = Column(VARCHAR(80),   nullable=True)
    created_at = Column(DATETIME(fsp=6), nullable=False)
