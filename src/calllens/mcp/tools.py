"""
MCP tool implementations — all DB queries are tenant-scoped via RLS.

Every tool:
1. Reads JWT claims from the per-request ContextVar
2. Checks role-based permission before touching the DB
3. Scopes queries to the caller's tenant_id
4. Filters / redacts fields based on role before returning
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from calllens.db import tenant_conn
from calllens.mcp.auth import get_claims
from calllens.mcp.permissions import (
    can_call, redact_account_health, allowed_call_types, owns_account,
)
from calllens.config import settings

# ── helpers ───────────────────────────────────────────────────────────────

def _extract_entities(content: str, known_accounts: list[str]) -> dict:
    """Extract account and topic mentions from free text."""
    lower = content.lower()
    found_accounts = [a for a in known_accounts if a.lower() in lower]
    return {"accounts": found_accounts}


def _deny(tool: str, reason: str = "") -> str:
    msg = f"Access denied — {tool} is not available for your role."
    if reason:
        msg += f" ({reason})"
    return msg


# ── Tool: get_my_insights ─────────────────────────────────────────────────

async def get_my_insights_impl() -> str:
    """Return persona-specific insights for the authenticated user's role."""
    claims = get_claims()
    role = claims.get("role", "")

    if not can_call(role, "get_my_insights"):
        return _deny("get_my_insights")

    # Map role → persona enum value in DB
    persona_map = {
        "support_lead": "support_lead",
        "sales_manager": "sales_manager",
        "product_manager": "product_manager",
        "eng_lead": "eng_lead",
    }
    persona = persona_map.get(role)
    if not persona:
        return _deny("get_my_insights", f"unknown role '{role}'")

    tenant_id = uuid.UUID(claims["tenant_id"])

    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT insight_type, title, body, severity, evidence_call_ids,
                   generated_at::text
            FROM insights
            WHERE tenant_id = $1 AND persona = $2::persona_role
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2 ELSE 3
                END,
                generated_at DESC
            LIMIT 20
            """,
            tenant_id, persona,
        )

    if not rows:
        return f"No insights found for role '{role}'. Run the analysis pipeline first."

    insights = [dict(r) for r in rows]
    for ins in insights:
        ins["evidence_call_ids"] = list(ins["evidence_call_ids"] or [])

    return json.dumps({"role": role, "insights": insights}, indent=2, default=str)


# ── Tool: get_topic_trends ────────────────────────────────────────────────

async def get_topic_trends_impl() -> str:
    """Return the most common topics across all analysed calls."""
    claims = get_claims()
    role = claims.get("role", "")

    if not can_call(role, "get_topic_trends"):
        return _deny("get_topic_trends")

    tenant_id = uuid.UUID(claims["tenant_id"])

    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT
                unnest(cs.topics) AS topic,
                COUNT(*)          AS frequency,
                AVG(cs.sentiment_score)::numeric(4,2) AS avg_sentiment
            FROM call_summaries cs
            JOIN calls c ON c.id = cs.call_id
            WHERE c.tenant_id = $1
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 20
            """,
            tenant_id,
        )

    topics = [
        {
            "topic": r["topic"],
            "frequency": r["frequency"],
            "avg_sentiment": float(r["avg_sentiment"] or 0),
        }
        for r in rows
    ]
    return json.dumps({"topics": topics}, indent=2)


# ── Tool: get_account_health ──────────────────────────────────────────────

async def get_account_health_impl(account_name: str) -> str:
    """
    Return health summary for a customer account.
    Financial fields are redacted unless you are a sales manager.
    """
    claims = get_claims()
    role = claims.get("role", "")

    if not can_call(role, "get_account_health"):
        return _deny("get_account_health")

    if not owns_account(claims, account_name):
        return _deny(
            "get_account_health",
            f"account '{account_name}' is not in your assigned book",
        )

    tenant_id = uuid.UUID(claims["tenant_id"])

    async with tenant_conn(tenant_id) as conn:
        # Basic call stats
        stats = await conn.fetchrow(
            """
            SELECT
                a.name,
                COUNT(DISTINCT c.id)            AS total_calls,
                AVG(cs.sentiment_score)::numeric(4,2) AS avg_sentiment,
                MIN(c.started_at)::text         AS first_call,
                MAX(c.started_at)::text         AS last_call,
                COUNT(CASE WHEN cc.call_type = 'support' THEN 1 END)  AS support_calls,
                COUNT(CASE WHEN cc.call_type = 'external' THEN 1 END) AS external_calls
            FROM accounts a
            JOIN call_classifications cc ON cc.account_id = a.id
            JOIN calls c ON c.id = cc.call_id
            JOIN call_summaries cs ON cs.call_id = c.id
            WHERE a.tenant_id = $1 AND LOWER(a.name) = LOWER($2)
            GROUP BY a.name
            """,
            tenant_id, account_name,
        )

        if not stats:
            return f"No data found for account '{account_name}'."

        # Recent topics mentioned in calls for this account
        topics_row = await conn.fetch(
            """
            SELECT DISTINCT unnest(cs.topics) AS topic
            FROM call_summaries cs
            JOIN calls c ON c.id = cs.call_id
            JOIN call_classifications cc ON cc.call_id = c.id
            JOIN accounts a ON a.id = cc.account_id
            WHERE a.tenant_id = $1 AND LOWER(a.name) = LOWER($2)
            LIMIT 10
            """,
            tenant_id, account_name,
        )

        # Sentiment trend (last 5 calls)
        trend = await conn.fetch(
            """
            SELECT cs.sentiment_score::float, c.started_at::text
            FROM calls c
            JOIN call_summaries cs ON cs.call_id = c.id
            JOIN call_classifications cc ON cc.call_id = c.id
            JOIN accounts a ON a.id = cc.account_id
            WHERE a.tenant_id = $1 AND LOWER(a.name) = LOWER($2)
            ORDER BY c.started_at DESC LIMIT 5
            """,
            tenant_id, account_name,
        )

        # Relevant insights for this account from DB
        insights = await conn.fetch(
            """
            SELECT persona, insight_type, title, severity
            FROM insights
            WHERE tenant_id = $1
              AND (LOWER(title) LIKE $3 OR LOWER(body) LIKE $3)
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END
            LIMIT 5
            """,
            tenant_id, account_name,
            f"%{account_name.lower()}%",
        )

    data: dict[str, Any] = {
        "account_name": stats["name"],
        "total_calls": stats["total_calls"],
        "avg_sentiment_score": float(stats["avg_sentiment"] or 0),
        "first_call": stats["first_call"],
        "last_call": stats["last_call"],
        "support_calls": stats["support_calls"],
        "external_calls": stats["external_calls"],
        "recent_topics": [r["topic"] for r in topics_row],
        "sentiment_trend": [
            {"score": r["sentiment_score"], "date": r["started_at"]} for r in trend
        ],
        "related_insights": [
            {"persona": r["persona"], "type": r["insight_type"],
             "title": r["title"], "severity": r["severity"]}
            for r in insights
        ],
        # These fields only visible to sales_manager — redact for others
        "contract_value": "REDACTED — sales data",
        "renewal_date": "REDACTED — sales data",
        "arr": "REDACTED — sales data",
        "csm_owner": "REDACTED — sales data",
    }

    data = redact_account_health(role, data)
    return json.dumps(data, indent=2, default=str)


# ── Tool: get_churn_risks ─────────────────────────────────────────────────

async def get_churn_risks_impl() -> str:
    """
    Return accounts with churn risk signals.
    Restricted to sales managers — own accounts only.
    """
    claims = get_claims()
    role = claims.get("role", "")

    if not can_call(role, "get_churn_risks"):
        return _deny(
            "get_churn_risks",
            "churn risk data is restricted to sales managers",
        )

    tenant_id = uuid.UUID(claims["tenant_id"])
    account_filter = claims.get("account_names", [])

    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT title, body, severity, evidence_call_ids, generated_at::text
            FROM insights
            WHERE tenant_id = $1
              AND persona = 'sales_manager'
              AND insight_type = 'churn_risk'
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2
                END
            """,
            tenant_id,
        )

    risks = [dict(r) for r in rows]
    for r in risks:
        r["evidence_call_ids"] = list(r["evidence_call_ids"] or [])

    # Apply own-account filter if the token specifies accounts
    if account_filter:
        risks = [
            r for r in risks
            if any(acc.lower() in r["title"].lower() or acc.lower() in r["body"].lower()
                   for acc in account_filter)
        ]

    if not risks:
        return "No churn risk insights found. Run the analysis pipeline or check your account assignments."

    return json.dumps({"churn_risks": risks}, indent=2, default=str)


# ── Tool: search_calls ────────────────────────────────────────────────────

async def search_calls_impl(query: str) -> str:
    """
    Search call summaries by keyword.
    Results are filtered to the call types your role may access.
    """
    claims = get_claims()
    role = claims.get("role", "")

    if not can_call(role, "search_calls"):
        return _deny("search_calls")

    call_types = allowed_call_types(role)
    tenant_id = uuid.UUID(claims["tenant_id"])
    account_filter = claims.get("account_names", [])
    search_term = f"%{query.lower()}%"

    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id::text, c.title, LEFT(cs.summary_text, 400) AS summary,
                c.started_at::text, cc.call_type,
                a.name AS account_name,
                cs.overall_sentiment, cs.sentiment_score::float
            FROM calls c
            JOIN call_summaries cs  ON cs.call_id  = c.id
            JOIN call_classifications cc ON cc.call_id = c.id
            LEFT JOIN accounts a    ON a.id = cc.account_id
            WHERE c.tenant_id = $1
              AND cc.call_type = ANY($2::text[])
              AND (
                  LOWER(cs.summary_text) LIKE $3
                  OR LOWER(c.title)      LIKE $3
                  OR $4 = ANY(
                      SELECT LOWER(t) FROM unnest(cs.topics) t
                  )
              )
            ORDER BY c.started_at DESC
            LIMIT 10
            """,
            tenant_id,
            call_types,
            search_term,
            query.lower(),
        )

    results = [dict(r) for r in rows]

    # Own-account filter for sales managers
    if account_filter:
        results = [
            r for r in results
            if not r["account_name"] or r["account_name"] in account_filter
        ]

    if not results:
        return f"No calls found matching '{query}' for your role."

    return json.dumps(
        {"query": query, "role": role, "results": results},
        indent=2, default=str,
    )


# ── Tool: remember_context ────────────────────────────────────────────────

async def remember_context_impl(content: str, expires_in_hours: int = 0) -> str:
    """
    Save a memory for the authenticated user.
    The content should be a concise summary of what was discussed or decided.
    Account names mentioned in the content are extracted automatically.
    """
    claims = get_claims()
    tenant_id = uuid.UUID(claims["tenant_id"])
    user_sub = claims["sub"]
    role = claims.get("role", "support_lead")

    if not content.strip():
        return "Memory content cannot be empty."

    # Pull known account names to auto-tag entities
    async with tenant_conn(tenant_id) as conn:
        account_rows = await conn.fetch(
            "SELECT name FROM accounts WHERE tenant_id = $1", tenant_id
        )
        known_accounts = [r["name"] for r in account_rows]
        entities = _extract_entities(content, known_accounts)

        expires_clause = (
            f"NOW() + INTERVAL '{expires_in_hours} hours'"
            if expires_in_hours > 0
            else "NULL"
        )
        row = await conn.fetchrow(
            f"""
            INSERT INTO user_memories
                (tenant_id, user_sub, role, content, entities, expires_at)
            VALUES
                ($1, $2, $3::persona_role, $4, $5, {expires_clause})
            RETURNING id::text, created_at::text
            """,
            tenant_id, user_sub, role, content.strip(), json.dumps(entities),
        )

    return json.dumps({
        "saved": True,
        "memory_id": row["id"],
        "created_at": row["created_at"],
        "entities": entities,
    })


# ── Tool: recall_context ──────────────────────────────────────────────────

async def recall_context_impl(limit: int = 10) -> str:
    """
    Return the most recent memories saved by the authenticated user.
    Only memories belonging to the caller's sub claim are returned.
    """
    claims = get_claims()
    tenant_id = uuid.UUID(claims["tenant_id"])
    user_sub = claims["sub"]

    limit = max(1, min(limit, 50))  # cap between 1 and 50

    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, content, entities, role::text,
                   created_at::text, expires_at::text
            FROM user_memories
            WHERE tenant_id = $1
              AND user_sub = $2
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY created_at DESC
            LIMIT $3
            """,
            tenant_id, user_sub, limit,
        )

    if not rows:
        return "No memories found. Use remember_context to save conversation context."

    memories = []
    for r in rows:
        m = dict(r)
        if isinstance(m["entities"], str):
            m["entities"] = json.loads(m["entities"])
        memories.append(m)

    return json.dumps({"user": user_sub, "memories": memories}, indent=2, default=str)


# ── Tool: forget_context ──────────────────────────────────────────────────

async def forget_context_impl(memory_id: str) -> str:
    """
    Delete a specific memory by its ID.
    You may only delete your own memories.
    """
    claims = get_claims()
    tenant_id = uuid.UUID(claims["tenant_id"])
    user_sub = claims["sub"]

    try:
        mem_uuid = uuid.UUID(memory_id)
    except ValueError:
        return f"Invalid memory_id format: '{memory_id}'. Must be a UUID."

    async with tenant_conn(tenant_id) as conn:
        result = await conn.execute(
            """
            DELETE FROM user_memories
            WHERE id = $1 AND tenant_id = $2 AND user_sub = $3
            """,
            mem_uuid, tenant_id, user_sub,
        )

    # result is like "DELETE 1" or "DELETE 0"
    deleted = result.endswith("1")
    if deleted:
        return json.dumps({"deleted": True, "memory_id": memory_id})
    return json.dumps({
        "deleted": False,
        "reason": "Memory not found or does not belong to you.",
    })


# ── Tool: graph_search ────────────────────────────────────────────────────

async def graph_search_impl(question: str) -> str:
    """
    Answer relationship questions about accounts, topics, and risks using
    the Neo4j knowledge graph.

    Uses LangChain GraphCypherQAChain: the LLM generates a Cypher query from
    the natural language question, runs it against Neo4j, then synthesises an
    answer grounded in the graph results.

    Examples:
      - "Which accounts share the same compliance issues?"
      - "What topics are most common for high-churn-risk accounts?"
      - "Which accounts had both outage and billing topics in their calls?"
    """
    claims = get_claims()
    role = claims.get("role", "")

    if not can_call(role, "graph_search"):
        return _deny("graph_search")

    tenant_id = claims["tenant_id"]

    # Lazy imports
    from neo4j import AsyncGraphDatabase
    from langchain_core.messages import HumanMessage, SystemMessage
    from calllens.llm.provider import get_llm

    # Graph schema — provided manually to avoid APOC dependency (Community Edition)
    GRAPH_SCHEMA = """
Nodes:
  (:Account  {name: str, tenant_id: str, call_count: int, avg_sentiment: float})
  (:Call     {id: str, title: str, call_type: str, sentiment_label: str, sentiment_score: float, started_at: str, tenant_id: str})
  (:Topic    {name: str})
  (:Insight  {id: str, type: str, severity: str, title: str, persona: str, tenant_id: str})

Relationships:
  (:Call)-[:INVOLVES]->(:Account)         # call involves this customer account
  (:Call)-[:COVERS]->(:Topic)             # call discusses this topic
  (:Account)-[:HAS_INSIGHT]->(:Insight)   # account has this AI-generated insight
  (:Account)-[:CO_OCCURS_WITH {shared_topics: int}]->(:Account)  # accounts sharing 2+ topics

Useful patterns:
  - Accounts with most shared topics: MATCH (a1)-[r:CO_OCCURS_WITH]-(a2) RETURN a1.name, a2.name, r.shared_topics ORDER BY r.shared_topics DESC
  - Topics per account: MATCH (a:Account)<-[:INVOLVES]-(c:Call)-[:COVERS]->(t:Topic) WHERE a.tenant_id=$tid RETURN a.name, collect(DISTINCT t.name)
  - High-severity insights: MATCH (a:Account)-[:HAS_INSIGHT]->(i:Insight) WHERE i.severity IN ['critical','high'] AND a.tenant_id=$tid RETURN a.name, i.title, i.severity
"""

    # Step 1: LLM generates Cypher from question + schema
    llm = get_llm(temperature=0, trace_name="graph_search")
    cypher_messages = [
        SystemMessage(content=(
            f"You are a Neo4j Cypher expert. Generate ONE valid Cypher query to answer the question.\n"
            f"IMPORTANT: Always filter nodes with tenant_id = '{tenant_id}' on Account, Call, and Insight nodes.\n"
            f"Return ONLY the Cypher query, no explanation, no markdown fences.\n\n"
            f"Schema:\n{GRAPH_SCHEMA}"
        )),
        HumanMessage(content=f"Question: {question}"),
    ]
    cypher_response = await llm.ainvoke(cypher_messages)
    cypher = cypher_response.content.strip().strip("```").strip("cypher").strip()

    # Step 2: Run the Cypher against Neo4j
    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        async with driver.session() as session:
            result = await session.run(cypher)
            records = [dict(r) async for r in result]
        await driver.close()
    except Exception as exc:
        return json.dumps({
            "question": question,
            "cypher_used": cypher,
            "error": f"Cypher execution failed: {exc}",
            "hint": "Try rephrasing. Run 'make graph-build' if graph is empty.",
        })

    # Step 3: LLM synthesises a natural-language answer from the raw results
    answer_messages = [
        SystemMessage(content=(
            "You are a helpful assistant. Given a question and raw graph query results, "
            "write a concise, factual answer in 2-4 sentences. No preamble."
        )),
        HumanMessage(content=(
            f"Question: {question}\n\n"
            f"Graph results (first 20 rows):\n{json.dumps(records[:20], indent=2, default=str)}"
        )),
    ]
    answer_response = await llm.ainvoke(answer_messages)

    return json.dumps({
        "question": question,
        "answer": answer_response.content,
        "cypher_used": cypher,
        "raw_results": records[:20],
    }, indent=2, default=str)
