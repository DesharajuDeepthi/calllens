"""Pipeline state and structured output models."""

from __future__ import annotations
from typing import TypedDict, Literal, Annotated
import operator
from pydantic import BaseModel, Field


# ── LLM output schemas (validated before entering state) ──────────────────
# These are used for LLM structured output ONLY.
# State stores plain dicts (serialisation-safe for LangGraph checkpointing).

class Classification(BaseModel):
    call_id: str
    meeting_id: str
    call_type: Literal["support", "external", "internal"]
    account_name: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class TopicCluster(BaseModel):
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    call_ids: list[str] = Field(default_factory=list)
    frequency: int
    trend: Literal["increasing", "stable", "decreasing"] = "stable"


class RiskSignal(BaseModel):
    account_name: str
    risk_level: Literal["low", "medium", "high", "critical"]
    signal_types: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    evidence_call_ids: list[str] = Field(default_factory=list)
    approved: bool = False


class PersonaInsight(BaseModel):
    persona: Literal["support_lead", "sales_manager", "product_manager", "eng_lead"]
    insight_type: str
    title: str
    body: str
    severity: Literal["low", "medium", "high", "critical"]
    evidence_call_ids: list[str] = Field(default_factory=list)


# ── Graph state ────────────────────────────────────────────────────────────
# All lists use plain dict so LangGraph can checkpoint them without msgpack issues.
# Only `errors` uses operator.add so parallel nodes can append safely.

class PipelineState(TypedDict):
    tenant_id: str
    batch_id: str

    calls_data: list[dict]          # compact dicts loaded from DB

    classifications: list[dict]     # Classification.model_dump()
    topics: list[dict]              # TopicCluster.model_dump()
    risks: list[dict]               # RiskSignal.model_dump()
    insights: list[dict]            # PersonaInsight.model_dump()

    needs_review: list[str]         # call_ids with low-confidence classification

    errors: Annotated[list[dict], operator.add]
