from os import getenv

from sqlalchemy     import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = (
    f"mysql+pymysql://"
    f"{getenv('MYSQL_USER')}:"
    f"{getenv('MYSQL_PASSWORD')}@"
    f"db:3306/"
    f"{getenv('MYSQL_DATABASE')}"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Base   = declarative_base()

SessionLocal   = sessionmaker(
    autocommit = False,
    autoflush  = False,
    bind       = engine,
)

def get_db():
    db = SessionLocal()

    try    : yield db
    finally: db.close()