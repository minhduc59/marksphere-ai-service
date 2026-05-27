from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    return session
