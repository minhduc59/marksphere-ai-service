from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    # Sized for concurrent multi-user scans: each run opens several short-lived
    # sessions. pool_pre_ping drops stale connections; pool_timeout fails fast
    # instead of hanging forever when the pool is saturated.
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_timeout=30,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
