"""
Graph builder — reads from Postgres and writes to Neo4j.

Entity model:
  (:Account   {name, tenant_id, call_count, avg_sentiment})
  (:Call      {id, title, call_type, sentiment_label, sentiment_score, started_at, tenant_id})
  (:Topic     {name})
  (:Insight   {id, type, severity, title, persona, tenant_id})

Relationships:
  (:Call)-[:INVOLVES]->(:Account)       call involves this customer account
  (:Call)-[:COVERS]->(:Topic)           call covers this topic
  (:Account)-[:HAS_INSIGHT]->(:Insight) account has this AI-generated insight
  (:Insight)-[:RELATED_TO]->(:Topic)    insight mentions this topic (keyword match)
  (:Account)-[:CO_OCCURS_WITH {count}]->(:Account)  two accounts share topic in same call
"""

from __future__ import annotations

import asyncpg
from calllens.config import settings
from calllens.graph.client import get_driver, ensure_schema


async def _pg_conn() -> asyncpg.Connection:
    return await asyncpg.connect(
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


async def build_graph(tenant_id: str) -> dict:
    """
    Pull all call data for the tenant from Postgres and write it into Neo4j.
    Fully idempotent — uses MERGE throughout so re-runs are safe.
    Returns counts of nodes and relationships written.
    """
    await ensure_schema()
    conn = await _pg_conn()
    driver = await get_driver()

    try:
        # ── 1. Load calls + accounts + topics from Postgres ──────────────────
        rows = await conn.fetch(
            """
            SELECT
                c.id::text          AS call_id,
                c.title,
                c.started_at::text  AS started_at,
                cc.call_type,
                cs.overall_sentiment AS sentiment_label,
                cs.sentiment_score::float AS sentiment_score,
                cs.topics,
                a.name              AS account_name
            FROM calls c
            JOIN call_summaries cs      ON cs.call_id = c.id
            JOIN call_classifications cc ON cc.call_id = c.id
            LEFT JOIN accounts a        ON a.id = cc.account_id
            WHERE c.tenant_id = $1::uuid
            ORDER BY c.started_at
            """,
            tenant_id,
        )

        # ── 2. Load insights ─────────────────────────────────────────────────
        insights = await conn.fetch(
            """
            SELECT
                id::text AS insight_id,
                insight_type,
                severity,
                title,
                body,
                persona::text
            FROM insights
            WHERE tenant_id = $1::uuid
            """,
            tenant_id,
        )

    finally:
        await conn.close()

    # ── 3. Write to Neo4j ─────────────────────────────────────────────────────
    stats = {"calls": 0, "accounts": 0, "topics": 0, "insights": 0,
             "involves": 0, "covers": 0, "has_insight": 0, "co_occurs": 0}

    async with driver.session() as session:
        # Upsert Calls + Accounts + INVOLVES + COVERS
        for r in rows:
            await session.run(
                """
                MERGE (c:Call {id: $call_id})
                SET c.title          = $title,
                    c.call_type      = $call_type,
                    c.sentiment_label = $sentiment_label,
                    c.sentiment_score = $sentiment_score,
                    c.started_at     = $started_at,
                    c.tenant_id      = $tenant_id

                WITH c
                FOREACH (topic IN $topics |
                    MERGE (t:Topic {name: topic})
                    MERGE (c)-[:COVERS]->(t)
                )
                """,
                call_id=r["call_id"], title=r["title"], call_type=r["call_type"],
                sentiment_label=r["sentiment_label"],
                sentiment_score=r["sentiment_score"],
                started_at=r["started_at"],
                tenant_id=tenant_id,
                topics=list(r["topics"] or []),
            )
            stats["calls"] += 1

            if r["account_name"]:
                await session.run(
                    """
                    MERGE (a:Account {name: $name, tenant_id: $tenant_id})
                    WITH a
                    MATCH (c:Call {id: $call_id})
                    MERGE (c)-[:INVOLVES]->(a)
                    """,
                    name=r["account_name"], tenant_id=tenant_id,
                    call_id=r["call_id"],
                )
                stats["accounts"] += 1
                stats["involves"] += 1

        # Upsert Insights + HAS_INSIGHT
        for ins in insights:
            # Derive account name from insight title (heuristic: first proper noun match)
            await session.run(
                """
                MERGE (i:Insight {id: $insight_id})
                SET i.type      = $insight_type,
                    i.severity  = $severity,
                    i.title     = $title,
                    i.persona   = $persona,
                    i.tenant_id = $tenant_id
                """,
                insight_id=ins["insight_id"], insight_type=ins["insight_type"],
                severity=ins["severity"], title=ins["title"],
                persona=ins["persona"], tenant_id=tenant_id,
            )
            stats["insights"] += 1

        # Link insights to accounts mentioned in their title
        account_names = await session.run(
            "MATCH (a:Account {tenant_id: $tid}) RETURN a.name AS name",
            tid=tenant_id,
        )
        names = [r["name"] async for r in account_names]

        for ins in insights:
            matched = [n for n in names if n and n.lower() in ins["title"].lower()]
            for name in matched:
                await session.run(
                    """
                    MATCH (a:Account {name: $name, tenant_id: $tenant_id})
                    MATCH (i:Insight {id: $insight_id})
                    MERGE (a)-[:HAS_INSIGHT]->(i)
                    """,
                    name=name, tenant_id=tenant_id,
                    insight_id=ins["insight_id"],
                )
                stats["has_insight"] += 1

        # Build CO_OCCURS_WITH — accounts that appear in calls sharing the same topic
        await session.run(
            """
            MATCH (a1:Account {tenant_id: $tid})<-[:INVOLVES]-(c:Call)-[:COVERS]->(t:Topic)
                  <-[:COVERS]-(c2:Call)-[:INVOLVES]->(a2:Account {tenant_id: $tid})
            WHERE a1 <> a2
            WITH a1, a2, count(DISTINCT t) AS shared_topics
            WHERE shared_topics >= 2
            MERGE (a1)-[r:CO_OCCURS_WITH]-(a2)
            SET r.shared_topics = shared_topics
            """,
            tid=tenant_id,
        )

        # Compute and store aggregates on Account nodes
        await session.run(
            """
            MATCH (a:Account {tenant_id: $tid})<-[:INVOLVES]-(c:Call)
            WITH a, count(c) AS call_count, avg(c.sentiment_score) AS avg_sentiment
            SET a.call_count    = call_count,
                a.avg_sentiment = round(avg_sentiment * 100) / 100
            """,
            tid=tenant_id,
        )

    return stats
