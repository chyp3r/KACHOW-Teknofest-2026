import logging
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# Create async engine for PostgreSQL connection
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for debug SQL query logging
    future=True,
    pool_pre_ping=True,  # Test connections before using
)

# Async session maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an asynchronous SQLAlchemy database session.

    Cleans up resources and rolls back on failure automatically.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error(
                f"Database transaction error: {e}. Rolling back.",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


async def verify_db_connection() -> bool:
    """Verify that we can establish a connection to the PostgreSQL database."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
            if val == 1:
                logger.info("PostgreSQL database connection verified successfully.")
                return True
            return False
    except Exception as e:
        logger.error(
            f"PostgreSQL database connection verification failed: {e}",
            exc_info=True,
        )
        return False
