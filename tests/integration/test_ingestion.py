"""
Integration test: ingest two real call folders and verify the DB rows.
Requires a running Postgres (docker compose up postgres -d).
"""

import asyncio
from pathlib import Path
from uuid import UUID
import pytest
import asyncpg

from calllens.config import settings
from calllens.db import get_pool, close_pool, tenant_conn
from calllens.ingestion.parser import parse_call_folder
from calllens.ingestion.writer import write_call

DATA_ROOT = Path("/Users/deepthidesharaju/Documents/Transcript Intelligence/data/raaw")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

pytestmark = [
    pytest.mark.skipif(not DATA_ROOT.exists(), reason="Transcript data not available"),
    pytest.mark.integration,
]


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def db_conn():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.tenant_id', $1, TRUE)", str(TENANT_ID)
        )
        yield conn
    await close_pool()


async def test_ingest_two_calls(db_conn):
    folders = sorted([d for d in DATA_ROOT.iterdir() if d.is_dir()])[:2]

    for folder in folders:
        parsed = parse_call_folder(folder)
        async with db_conn.transaction():
            call_id = await write_call(db_conn, parsed, TENANT_ID)
        assert isinstance(call_id, UUID)

        # Verify call row
        row = await db_conn.fetchrow("SELECT * FROM calls WHERE id = $1", call_id)
        assert row is not None
        assert row["meeting_id"] == parsed.meeting_info.meeting_id
        assert row["content_hash"] == parsed.content_hash

        # Verify summary row
        summary = await db_conn.fetchrow(
            "SELECT * FROM call_summaries WHERE call_id = $1", call_id
        )
        assert summary is not None
        assert summary["summary_text"] == parsed.summary.summary

        # Verify participants
        participants = await db_conn.fetch(
            "SELECT email FROM participants WHERE call_id = $1", call_id
        )
        assert len(participants) > 0

        # Verify transcript turns
        turns = await db_conn.fetch(
            "SELECT COUNT(*) as n FROM transcript_turns WHERE call_id = $1", call_id
        )
        assert turns[0]["n"] == len(parsed.transcript.data)


async def test_ingest_is_idempotent(db_conn):
    """Ingesting the same folder twice must not duplicate rows."""
    folder = sorted([d for d in DATA_ROOT.iterdir() if d.is_dir()])[0]
    parsed = parse_call_folder(folder)

    async with db_conn.transaction():
        id1 = await write_call(db_conn, parsed, TENANT_ID)
    async with db_conn.transaction():
        id2 = await write_call(db_conn, parsed, TENANT_ID)

    assert id1 == id2

    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM calls WHERE meeting_id = $1 AND tenant_id = $2",
        parsed.meeting_info.meeting_id,
        TENANT_ID,
    )
    assert count == 1
