"""
LangGraph node implementations.

Each node receives the full PipelineState and returns a partial state update dict.
All agent outputs are stored as plain dicts (safe for LangGraph checkpointing).
LLM failures are caught and recorded in errors — one bad call never kills the batch.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from calllens.agents.prompts import (
    CLASSIFIER_SYSTEM, CLASSIFIER_USER,
    TOPIC_ANALYST_SYSTEM, TOPIC_ANALYST_USER,
    RISK_SIGNALS_SYSTEM, RISK_SIGNALS_USER,
    PERSONA_USER, PERSONA_CONFIGS,
)
from calllens.agents.state import (
    Classification, TopicCluster, RiskSignal, PersonaInsight, PipelineState,
)
from calllens.config import settings
from calllens.db import tenant_conn
from calllens.llm.provider import get_llm
from calllens.observability.telemetry import get_tracer
from langgraph.types import interrupt

_tracer = get_tracer("calllens.pipeline")


# ── LLM helpers ────────────────────────────────────────────────────────────

def _chain(schema: type[BaseModel], batch_id: str = "", node: str = ""):
    return get_llm(
        trace_name=f"pipeline/{batch_id}" if batch_id else "calllens",
        metadata={"node": node, "batch_id": batch_id},
    ).with_structured_output(schema)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ValidationError, ValueError, Exception)),
    reraise=True,
)
async def _invoke(chain, messages: list) -> BaseModel:
    return await chain.ainvoke(messages)


# ── Node: load_calls ────────────────────────────────────────────────────────

async def load_calls(state: PipelineState) -> dict:
    with _tracer.start_as_current_span("node.load_calls") as span:
        span.set_attribute("batch_id", state.get("batch_id", ""))
    tenant_id = uuid.UUID(state["tenant_id"])

    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id::text           AS call_id,
                c.meeting_id,
                c.title,
                c.started_at,
                cs.summary_text,
                cs.topics,
                cs.overall_sentiment,
                cs.sentiment_score,
                cs.action_items,
                ARRAY_AGG(p.email ORDER BY p.email)
                    FILTER (WHERE p.email IS NOT NULL) AS participant_emails
            FROM calls c
            JOIN call_summaries cs ON cs.call_id = c.id
            LEFT JOIN participants p ON p.call_id = c.id
            GROUP BY c.id, c.meeting_id, c.title, c.started_at,
                     cs.summary_text, cs.topics, cs.overall_sentiment,
                     cs.sentiment_score, cs.action_items
            ORDER BY c.started_at ASC
            """
        )

    calls_data = []
    for r in rows:
        d = dict(r)
        d["started_at"] = d["started_at"].isoformat()
        d["topics"] = list(d["topics"] or [])
        d["action_items"] = list(d["action_items"] or [])
        d["participant_emails"] = list(d["participant_emails"] or [])
        if d.get("sentiment_score") is not None:
            d["sentiment_score"] = float(d["sentiment_score"])
        calls_data.append(d)

    return {
        "calls_data": calls_data,
        "classifications": [],
        "topics": [],
        "risks": [],
        "insights": [],
        "errors": [],
        "needs_review": [],
    }


# ── Node: classify_batch ────────────────────────────────────────────────────

async def _classify_one(call: dict) -> dict:
    """Returns a Classification dict or an error dict."""
    participants = ", ".join(call["participant_emails"])
    messages = [
        SystemMessage(content=CLASSIFIER_SYSTEM),
        HumanMessage(content=CLASSIFIER_USER.format(
            title=call["title"],
            participants=participants,
            summary=call["summary_text"][:600],
            topics=", ".join(call["topics"]),
        )),
    ]
    try:
        result: Classification = await _invoke(_chain(Classification), messages)
        d = result.model_dump()
        d["call_id"] = call["call_id"]
        d["meeting_id"] = call["meeting_id"]
        return {"ok": d}
    except Exception as exc:
        return {"err": {"stage": "classify", "call_id": call["call_id"], "message": str(exc)}}


async def classify_batch(state: PipelineState) -> dict:
    batch_id = state.get("batch_id", "")
    with _tracer.start_as_current_span("node.classify_batch") as span:
        span.set_attribute("batch_id", batch_id)
        span.set_attribute("call_count", len(state["calls_data"]))

    semaphore = asyncio.Semaphore(10)

    async def bounded(call: dict):
        async with semaphore:
            return await _classify_one(call)

    results = await asyncio.gather(*[bounded(c) for c in state["calls_data"]])

    classifications = [r["ok"] for r in results if "ok" in r]
    errors = [r["err"] for r in results if "err" in r]
    needs_review = [
        c["call_id"]
        for c in classifications
        if c["confidence"] < settings.classifier_confidence_threshold
    ]

    return {
        "classifications": classifications,
        "errors": errors,
        "needs_review": needs_review,
    }


# ── Node: classification_review_gate ───────────────────────────────────────

def classification_review_gate(state: PipelineState) -> dict:
    if not state["needs_review"]:
        return {}

    uncertain = {
        c["call_id"]: c
        for c in state["classifications"]
        if c["call_id"] in state["needs_review"]
    }

    corrections: dict = interrupt({
        "type": "classification_review",
        "message": (
            f"{len(uncertain)} calls have confidence "
            f"< {settings.classifier_confidence_threshold}. "
            "Return {call_id: {call_type, account_name}} corrections."
        ),
        "uncertain_calls": uncertain,
    })

    if not corrections:
        return {"needs_review": []}

    updated = []
    for c in state["classifications"]:
        fix = corrections.get(c["call_id"])
        if fix:
            c = {**c, **fix, "confidence": 1.0}
        updated.append(c)

    return {"classifications": updated, "needs_review": []}


# ── Node: analyze_topics ────────────────────────────────────────────────────

class _TopicsOutput(BaseModel):
    clusters: list[TopicCluster]


async def analyze_topics(state: PipelineState) -> dict:
    cls_map = {c["call_id"]: c for c in state["classifications"]}
    call_rows = [
        {
            "call_id": call["call_id"],
            "started_at": call["started_at"],
            "call_type": cls_map.get(call["call_id"], {}).get("call_type", "unknown"),
            "account": cls_map.get(call["call_id"], {}).get("account_name"),
            "topics": call["topics"],
            "sentiment_score": call["sentiment_score"],
        }
        for call in state["calls_data"]
    ]

    messages = [
        SystemMessage(content=TOPIC_ANALYST_SYSTEM),
        HumanMessage(content=TOPIC_ANALYST_USER.format(
            n_calls=len(call_rows),
            calls_json=json.dumps(call_rows, indent=1),
        )),
    ]

    try:
        result: _TopicsOutput = await _invoke(_chain(_TopicsOutput), messages)
        return {"topics": [t.model_dump() for t in result.clusters]}
    except Exception as exc:
        return {
            "topics": [],
            "errors": [{"stage": "analyze_topics", "call_id": None, "message": str(exc)}],
        }


# ── Node: detect_risks ──────────────────────────────────────────────────────

async def _risk_for_account(account_name: str, calls: list[dict]) -> dict:
    messages = [
        SystemMessage(content=RISK_SIGNALS_SYSTEM),
        HumanMessage(content=RISK_SIGNALS_USER.format(
            account_name=account_name,
            calls_json=json.dumps(calls, indent=1),
        )),
    ]
    try:
        result: RiskSignal = await _invoke(_chain(RiskSignal), messages)
        d = result.model_dump()
        d["account_name"] = account_name
        return {"ok": d}
    except Exception as exc:
        return {"err": {"stage": "detect_risks", "call_id": None, "message": f"{account_name}: {exc}"}}


async def detect_risks(state: PipelineState) -> dict:
    cls_map = {c["call_id"]: c for c in state["classifications"]}
    data_map = {c["call_id"]: c for c in state["calls_data"]}

    accounts: dict[str, list[dict]] = {}
    for call_id, cls in cls_map.items():
        if not cls.get("account_name"):
            continue
        call = data_map.get(call_id)
        if not call:
            continue
        accounts.setdefault(cls["account_name"], []).append({
            "call_id": call_id,
            "started_at": call["started_at"],
            "call_type": cls["call_type"],
            "summary": call["summary_text"][:400],
            "sentiment_score": call["sentiment_score"],
            "overall_sentiment": call["overall_sentiment"],
            "topics": call["topics"],
            "action_items": call["action_items"],
        })

    multi_call = {acc: calls for acc, calls in accounts.items() if len(calls) >= 2}
    semaphore = asyncio.Semaphore(5)

    async def bounded(acc: str, calls: list[dict]):
        async with semaphore:
            return await _risk_for_account(
                acc, sorted(calls, key=lambda x: x["started_at"])
            )

    results = await asyncio.gather(*[
        bounded(acc, calls) for acc, calls in multi_call.items()
    ])

    risks = [r["ok"] for r in results if "ok" in r]
    errors = [r["err"] for r in results if "err" in r]
    return {"risks": risks, "errors": errors}


# ── Node: risk_review_gate ──────────────────────────────────────────────────

def risk_review_gate(state: PipelineState) -> dict:
    high_risks = [r for r in state["risks"] if r["risk_level"] in ("high", "critical")]

    if not high_risks:
        approved = [{**r, "approved": True} for r in state["risks"]]
        return {"risks": approved}

    approved_accounts: list[str] = interrupt({
        "type": "risk_review",
        "message": (
            f"{len(high_risks)} high/critical risk signals need approval. "
            "Return a list of account names to approve."
        ),
        "risks": high_risks,
    })

    approved_set = set(approved_accounts or [])
    updated = [
        {**r, "approved": True}
        if r["risk_level"] in ("low", "medium") or r["account_name"] in approved_set
        else r
        for r in state["risks"]
    ]
    return {"risks": updated}


# ── Node: write_all_insights ────────────────────────────────────────────────

# Looser schema for LLM output — no Literal fields the model has to guess.
# We set persona and coerce severity ourselves after the call.
class _RawInsight(BaseModel):
    insight_type: str = "general"
    title: str
    body: str
    severity: str = "medium"
    evidence_call_ids: list[str] = Field(default_factory=list)

class _InsightsOutput(BaseModel):
    insights: list[_RawInsight]


_VALID_SEVERITY = {"low", "medium", "high", "critical"}


async def _insights_for_persona(persona_key: str, state: PipelineState) -> dict:
    config = PERSONA_CONFIGS[persona_key]
    cls_map = {c["call_id"]: c for c in state["classifications"]}

    calls_compact = [
        {
            "call_id": c["call_id"],
            "title": c["title"],
            "call_type": cls_map.get(c["call_id"], {}).get("call_type", "unknown"),
            "account": cls_map.get(c["call_id"], {}).get("account_name"),
            "summary": c["summary_text"][:300],
            "sentiment": c["overall_sentiment"],
        }
        for c in state["calls_data"]
    ]

    approved_risks = [r for r in state["risks"] if r.get("approved")]

    messages = [
        SystemMessage(content=config["system"]),
        HumanMessage(content=PERSONA_USER.format(
            topics_json=json.dumps(state["topics"], indent=1),
            risks_json=json.dumps(approved_risks, indent=1),
            calls_json=json.dumps(calls_compact, indent=1),
        )),
    ]

    try:
        result: _InsightsOutput = await _invoke(_chain(_InsightsOutput), messages)
        insights = []
        for raw in result.insights:
            d = raw.model_dump()
            d["persona"] = config["persona"]
            d["severity"] = d["severity"] if d["severity"] in _VALID_SEVERITY else "medium"
            insights.append(d)
        return {"ok": insights}
    except Exception as exc:
        return {"err": {"stage": f"write_insights_{persona_key}", "call_id": None, "message": str(exc)}}


async def write_all_insights(state: PipelineState) -> dict:
    results = await asyncio.gather(
        *[_insights_for_persona(key, state) for key in PERSONA_CONFIGS],
        return_exceptions=True,
    )

    insights: list[dict] = []
    errors: list[dict] = []
    for key, r in zip(PERSONA_CONFIGS.keys(), results):
        if isinstance(r, Exception):
            errors.append({"stage": f"write_insights_{key}", "call_id": None, "message": str(r)})
        elif "ok" in r:
            insights.extend(r["ok"])
        else:
            errors.append(r["err"])

    return {"insights": insights, "errors": errors}


# ── Node: persist_insights ──────────────────────────────────────────────────

async def persist_insights(state: PipelineState) -> dict:
    tenant_id = uuid.UUID(state["tenant_id"])
    batch_id = state["batch_id"]

    async with tenant_conn(tenant_id) as conn:
        async with conn.transaction():
            for cls in state["classifications"]:
                account_id = None
                if cls.get("account_name"):
                    account_id = await conn.fetchval(
                        """
                        INSERT INTO accounts (tenant_id, name)
                        VALUES ($1, $2)
                        ON CONFLICT (tenant_id, name) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                        """,
                        tenant_id, cls["account_name"],
                    )
                await conn.execute(
                    """
                    INSERT INTO call_classifications
                        (tenant_id, call_id, call_type, account_id, confidence, needs_review)
                    VALUES ($1, $2::uuid, $3, $4, $5, $6)
                    ON CONFLICT (call_id)
                    DO UPDATE SET
                        call_type=EXCLUDED.call_type, account_id=EXCLUDED.account_id,
                        confidence=EXCLUDED.confidence, needs_review=EXCLUDED.needs_review,
                        classified_at=NOW()
                    """,
                    tenant_id,
                    cls["call_id"],
                    cls["call_type"],
                    account_id,
                    cls["confidence"],
                    cls["call_id"] in (state.get("needs_review") or []),
                )

            for ins in state["insights"]:
                await conn.execute(
                    """
                    INSERT INTO insights
                        (tenant_id, persona, insight_type, title, body,
                         severity, evidence_call_ids, batch_id)
                    VALUES ($1, $2::persona_role, $3, $4, $5, $6, $7::uuid[], $8)
                    ON CONFLICT DO NOTHING
                    """,
                    tenant_id,
                    ins["persona"],
                    ins["insight_type"],
                    ins["title"],
                    ins["body"],
                    ins["severity"],
                    ins["evidence_call_ids"],
                    batch_id,
                )

    return {}
