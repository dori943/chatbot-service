from os import getenv

from sqlalchemy.engine      import URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm         import declarative_base

DATABASE_URL = URL.create(
    drivername = "mysql+aiomysql",
    username   = getenv("MYSQL_USER"),
    password   = getenv("MYSQL_PASSWORD"),
    host       = "db",
    port       = 3306,
    database   = getenv("MYSQL_DATABASE"),
    query      = {"charset": "utf8mb4"},
)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
Base   = declarative_base()

SessionLocal = async_sessionmaker(
    autoflush        = False,
    expire_on_commit = False,
    bind             = engine,
)

async def get_db():
    async with SessionLocal() as db:
        yield db
