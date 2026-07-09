"""Database connection pool and RLS session helper."""

import asyncpg
from contextlib import asynccontextmanager
from uuid import UUID
from calllens.config import settings


_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=(
                f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
                f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
            ),
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def tenant_conn(tenant_id: UUID):
    """
    Yields an asyncpg connection with app.tenant_id set as a session variable.
    Every query on this connection is automatically filtered by RLS policies.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # is_local=FALSE → session-level (persists across autocommit statements).
        # TRUE would scope the setting to the current transaction only, which is
        # lost immediately in asyncpg's autocommit mode.
        await conn.execute(
            "SELECT set_config('app.tenant_id', $1, FALSE)",
            str(tenant_id),
        )
        yield conn
