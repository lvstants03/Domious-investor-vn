import logging
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.config import settings
from src.database.models import Base

logger = logging.getLogger("dominus-investor.database.connection")

db_url = settings.DATABASE_URL
# Chuyen doi chuoi Render / Heroku / PostgreSQL sang asyncpg
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql+psycopg2://"):
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)

connect_args = {}
if "sqlite" in db_url:
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

async def init_db():
    """Khoi tao cac bang CSDL cho dominus-investor neu chua ton tai (dung cho dev/sqlite)"""
    try:
        async with engine.begin() as conn:
            # Chi tao neu chua co table
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error("Error initializing database tables: %s", str(e))

async def get_db():
    """Generator lay session dung cho FastAPI Dependency Injection"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e

@asynccontextmanager
async def get_db_session():
    """Context manager lay session an toan cho scripts / background tasks"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e
