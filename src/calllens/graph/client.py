"""Neo4j driver singleton and schema initialisation."""

from __future__ import annotations

from neo4j import AsyncGraphDatabase, AsyncDriver
from calllens.config import settings

_driver: AsyncDriver | None = None


async def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


# Cypher constraints + indexes — idempotent, safe to run on every startup
_SCHEMA_STATEMENTS = [
    # Community Edition: single-property uniqueness only (no composite NODE KEY)
    "CREATE CONSTRAINT call_id IF NOT EXISTS FOR (c:Call) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT insight_id IF NOT EXISTS FOR (i:Insight) REQUIRE i.id IS UNIQUE",
    "CREATE INDEX call_tenant IF NOT EXISTS FOR (c:Call) ON (c.tenant_id)",
    "CREATE INDEX account_tenant IF NOT EXISTS FOR (a:Account) ON (a.tenant_id)",
    "CREATE INDEX insight_tenant IF NOT EXISTS FOR (i:Insight) ON (i.tenant_id)",
    # Composite index for (tenant_id, name) lookups on Account
    "CREATE INDEX account_tenant_name IF NOT EXISTS FOR (a:Account) ON (a.tenant_id, a.name)",
]


async def ensure_schema() -> None:
    driver = await get_driver()
    async with driver.session() as session:
        for stmt in _SCHEMA_STATEMENTS:
            await session.run(stmt)
