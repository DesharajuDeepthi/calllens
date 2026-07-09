"""
Shared fixtures for eval tests.

Requires a running Postgres with the full pipeline already executed.
Mark: pytest -m eval
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from calllens.db import get_pool, close_pool, tenant_conn

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

pytestmark = pytest.mark.eval


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def all_classifications():
    """All call_classifications rows joined with call title."""
    async with tenant_conn(TENANT_ID) as conn:
        rows = await conn.fetch(
            """
            SELECT c.id::text, c.title, cc.call_type, cc.account_id::text,
                   a.name AS account_name
            FROM call_classifications cc
            JOIN calls c ON c.id = cc.call_id
            LEFT JOIN accounts a ON a.id = cc.account_id
            WHERE c.tenant_id = $1
            """,
            TENANT_ID,
        )
    return [dict(r) for r in rows]


@pytest.fixture(scope="session")
async def all_summaries():
    """All call_summaries rows joined with call title."""
    async with tenant_conn(TENANT_ID) as conn:
        rows = await conn.fetch(
            """
            SELECT c.id::text, c.title, cs.overall_sentiment,
                   cs.sentiment_score::float, LEFT(cs.summary_text, 600) AS summary_text
            FROM call_summaries cs
            JOIN calls c ON c.id = cs.call_id
            WHERE c.tenant_id = $1
            """,
            TENANT_ID,
        )
    return [dict(r) for r in rows]


@pytest.fixture(scope="session")
async def all_insights():
    """All insights rows for all personas."""
    async with tenant_conn(TENANT_ID) as conn:
        rows = await conn.fetch(
            """
            SELECT persona::text, insight_type, title, body, severity,
                   evidence_call_ids, generated_at::text
            FROM insights
            WHERE tenant_id = $1
            """,
            TENANT_ID,
        )
    results = [dict(r) for r in rows]
    for r in results:
        r["evidence_call_ids"] = list(r["evidence_call_ids"] or [])
    return results


@pytest.fixture(scope="session")
async def call_count():
    async with tenant_conn(TENANT_ID) as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM calls WHERE tenant_id = $1", TENANT_ID
        )


@pytest.fixture(scope="session")
async def insight_count():
    async with tenant_conn(TENANT_ID) as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM insights WHERE tenant_id = $1", TENANT_ID
        )
