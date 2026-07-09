"""Write a ParsedCall into Postgres. All operations are upserts — idempotent."""

import json
from uuid import UUID

import asyncpg

from calllens.ingestion.models import ParsedCall


_INTERNAL_DOMAIN = "aegiscloud.com"


async def write_call(
    conn: asyncpg.Connection,
    parsed: ParsedCall,
    tenant_id: UUID,
) -> UUID:
    """
    Upsert one call and all its related rows.
    Returns the call UUID (existing or newly inserted).
    Skips the call entirely if content_hash matches what's already stored
    (idempotency: re-ingesting the same folder is a no-op).
    """
    mi = parsed.meeting_info

    # Check idempotency: same content_hash = already ingested
    existing = await conn.fetchrow(
        "SELECT id, content_hash FROM calls WHERE tenant_id = $1 AND meeting_id = $2",
        tenant_id,
        mi.meeting_id,
    )
    if existing and existing["content_hash"] == parsed.content_hash:
        return existing["id"]   # sentinel: caller checks against this to count skips

    # Upsert call row
    call_id: UUID = await conn.fetchval(
        """
        INSERT INTO calls (tenant_id, meeting_id, title, organizer_email, host_email,
                           started_at, ended_at, duration_mins, raw_folder, content_hash)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (tenant_id, meeting_id)
        DO UPDATE SET title=EXCLUDED.title, content_hash=EXCLUDED.content_hash,
                      raw_folder=EXCLUDED.raw_folder, ingested_at=NOW()
        RETURNING id
        """,
        tenant_id,
        mi.meeting_id,
        mi.title,
        mi.organizer_email,
        mi.host,
        mi.start_time,
        mi.end_time,
        mi.duration,
        parsed.folder_path,
        parsed.content_hash,
    )

    # Delete and re-insert participants (cheap at 100 calls, avoids partial-update bugs)
    await conn.execute("DELETE FROM participants WHERE call_id = $1", call_id)
    for email in set(mi.all_emails):
        await conn.execute(
            """
            INSERT INTO participants (tenant_id, call_id, email, is_internal)
            VALUES ($1,$2,$3,$4)
            """,
            tenant_id,
            call_id,
            email.lower(),
            email.lower().endswith(f"@{_INTERNAL_DOMAIN}"),
        )

    # Upsert summary
    s = parsed.summary
    await conn.execute(
        """
        INSERT INTO call_summaries (tenant_id, call_id, summary_text, overall_sentiment,
                                    sentiment_score, topics, action_items, key_moments)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (call_id)
        DO UPDATE SET summary_text=EXCLUDED.summary_text,
                      overall_sentiment=EXCLUDED.overall_sentiment,
                      sentiment_score=EXCLUDED.sentiment_score,
                      topics=EXCLUDED.topics,
                      action_items=EXCLUDED.action_items,
                      key_moments=EXCLUDED.key_moments
        """,
        tenant_id,
        call_id,
        s.summary,
        s.overall_sentiment,
        s.sentiment_score,
        list(s.topics),
        list(s.action_items),
        json.dumps([m.model_dump() for m in s.key_moments]),
    )

    # Insert transcript turns (delete-then-insert for simplicity at this scale)
    await conn.execute("DELETE FROM transcript_turns WHERE call_id = $1", call_id)
    if parsed.transcript.data:
        await conn.executemany(
            """
            INSERT INTO transcript_turns
                (tenant_id, call_id, turn_index, speaker_name, speaker_id,
                 sentence, sentiment_type, start_time_secs, end_time_secs, confidence)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            [
                (
                    tenant_id,
                    call_id,
                    t.index,
                    t.speaker_name,
                    t.speaker_id,
                    t.sentence,
                    t.sentiment_type,
                    t.time,
                    t.end_time,
                    t.average_confidence,
                )
                for t in parsed.transcript.data
            ],
        )

    return call_id
