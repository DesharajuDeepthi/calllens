"""
CallLens MCP server.

Architecture:
  FastAPI app  →  JWT middleware (sets ContextVar claims)
               →  MCP SSE app (mounted at /mcp)

Every MCP tool call arrives through the SSE endpoint, which is already
behind the middleware, so claims are guaranteed to be present.

Run locally (inside Docker):
    uvicorn calllens.mcp.server:app --host 0.0.0.0 --port 8000

Or via Makefile:
    make mcp-up
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import jwt as pyjwt
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from calllens.mcp.auth import decode_token, set_claims
from calllens.mcp.dashboard import router as dashboard_router
from calllens.observability.telemetry import setup_tracing
from calllens.mcp.tools import (
    forget_context_impl,
    get_account_health_impl,
    get_churn_risks_impl,
    get_my_insights_impl,
    get_topic_trends_impl,
    recall_context_impl,
    remember_context_impl,
    search_calls_impl,
    graph_search_impl,
)

logger = structlog.get_logger(__name__)

# ── App lifespan — run once at startup ────────────────────────────────────

@asynccontextmanager
async def lifespan(app_: FastAPI):
    setup_tracing("calllens-mcp")
    yield


# ── MCP server instance ────────────────────────────────────────────────────

mcp = FastMCP("CallLens")


# ── Tool registrations ─────────────────────────────────────────────────────

@mcp.tool()
async def get_my_insights() -> str:
    """
    Return persona-specific insights generated from your company's call data.
    The insights shown depend on your role (support_lead, sales_manager,
    product_manager, eng_lead).
    """
    return await get_my_insights_impl()


@mcp.tool()
async def get_topic_trends() -> str:
    """
    Return the most frequently discussed topics across all analysed calls,
    ranked by frequency with average sentiment scores.
    """
    return await get_topic_trends_impl()


@mcp.tool()
async def get_account_health(account_name: str) -> str:
    """
    Return health metrics for a specific customer account.

    Args:
        account_name: Exact name of the customer account (case-insensitive).

    Financial fields (contract_value, renewal_date, arr, csm_owner) are
    only visible to sales managers. You must own the account to query it.
    """
    return await get_account_health_impl(account_name)


@mcp.tool()
async def get_churn_risks() -> str:
    """
    Return accounts showing churn risk signals.
    Restricted to sales managers only.
    """
    return await get_churn_risks_impl()


@mcp.tool()
async def search_calls(query: str) -> str:
    """
    Search call summaries and transcripts by keyword.

    Args:
        query: Keyword or phrase to search for.

    Results are filtered to the call types accessible to your role.
    """
    return await search_calls_impl(query)


@mcp.tool()
async def remember_context(content: str, expires_in_hours: int = 0) -> str:
    """
    Save a memory for your current session context.

    Use this after every meaningful exchange so future sessions can recall what
    was discussed, which accounts were reviewed, and what decisions were made.

    Args:
        content: A concise summary of what was discussed or decided.
        expires_in_hours: Auto-expire after N hours (0 = keep forever).
    """
    return await remember_context_impl(content, expires_in_hours)


@mcp.tool()
async def recall_context(limit: int = 10) -> str:
    """
    Retrieve your most recent saved memories.

    Call this at the start of each session to restore context from prior
    conversations — accounts reviewed, open questions, decisions made.

    Args:
        limit: Number of most recent memories to return (max 50).
    """
    return await recall_context_impl(limit)


@mcp.tool()
async def forget_context(memory_id: str) -> str:
    """
    Delete a specific memory by its ID.

    Args:
        memory_id: The UUID of the memory to delete (from recall_context results).
    """
    return await forget_context_impl(memory_id)


@mcp.tool()
async def graph_search(question: str) -> str:
    """
    Answer relationship and pattern questions about accounts, topics, and risks
    using the Neo4j knowledge graph.

    The graph captures:
      - Which accounts were involved in which calls
      - Which topics were discussed in each call
      - Which AI-generated insights are linked to which accounts
      - Which accounts co-occur across calls sharing the same topics

    Args:
        question: A natural language question about relationships or patterns.

    Examples:
        - "Which accounts share compliance issues?"
        - "What topics appear most in calls with negative sentiment?"
        - "Which accounts had both outage and billing discussions?"
        - "Which accounts are most connected to churn risk insights?"
    """
    return await graph_search_impl(question)


# ── FastAPI wrapper ────────────────────────────────────────────────────────

app = FastAPI(title="CallLens MCP Gateway", version="0.1.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
app.include_router(dashboard_router)  # /dashboard and /api/metrics (no auth)


@app.middleware("http")
async def jwt_middleware(request: Request, call_next: Any) -> Response:
    """
    Extract + validate the Bearer token from every request, then store claims
    in the ContextVar so MCP tools can read them without threading the token
    through function arguments.

    Unauthenticated requests to /health are allowed through.
    Everything else requires a valid token.
    """
    if request.url.path in ("/health", "/", "/docs", "/openapi.json", "/dashboard", "/api/metrics"):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "Missing Bearer token"},
        )

    token = auth.removeprefix("Bearer ").strip()
    try:
        claims = decode_token(token)
    except pyjwt.ExpiredSignatureError:
        return JSONResponse(status_code=401, content={"error": "Token expired"})
    except pyjwt.InvalidTokenError as exc:
        return JSONResponse(status_code=401, content={"error": f"Invalid token: {exc}"})

    set_claims(claims)
    return await call_next(request)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "calllens-mcp"}


# Mount the MCP SSE app under /mcp
# All MCP protocol traffic goes to /mcp/sse and /mcp/messages
mcp_asgi = mcp.sse_app()
app.mount("/mcp", mcp_asgi)
