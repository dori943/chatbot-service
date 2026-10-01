from sqlalchemy import Column, VARCHAR
from app.db     import Base

# ==============================================================================
# [사용자 계정 엔티티: Login]
# MySQL 'login' 테이블과 매핑되는 SQLAlchemy ORM 엔티티 클래스
# 1) id: 사용자 계정 아이디 (Primary Key, VARCHAR 50)
# 2) pw: Bcrypt 해시 문자열 저장 컬럼 (VARCHAR 255, 원본 평문 비밀번호는 저장하지 않음)
# ==============================================================================
class Login(Base):
    # 매핑할 데이터베이스 테이블 이름
    __tablename__ = "login"

    # 사용자 계정 아이디 (기본키)
    id = Column(VARCHAR(50),  primary_key=True)
    # Bcrypt 암호화된 비밀번호 해시 문자열
    pw = Column(VARCHAR(255), nullable=False)
