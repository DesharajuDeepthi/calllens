"""
LangGraph pipeline graph definition with Postgres checkpointing.

Graph flow:
  START
    → load_calls
    → classify_batch
    → classification_review_gate   (interrupt if low-confidence calls exist)
    → analyze_topics
    → detect_risks
    → risk_review_gate             (interrupt for human approval of high/critical risks)
    → write_all_insights
    → persist_insights
    → END
"""

from __future__ import annotations

import hashlib
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from calllens.agents.nodes import (
    load_calls,
    classify_batch,
    classification_review_gate,
    analyze_topics,
    detect_risks,
    risk_review_gate,
    write_all_insights,
    persist_insights,
)
from calllens.agents.state import PipelineState
from calllens.config import settings


class PipelineInterrupted(Exception):
    """Raised when the graph pauses at a HITL gate waiting for human input."""

    def __init__(self, batch_id: str, pending_node: str, interrupt_data: list):
        self.batch_id = batch_id
        self.pending_node = pending_node
        self.interrupt_data = interrupt_data
        super().__init__(f"Pipeline paused at '{pending_node}' (batch={batch_id})")


def _build_graph() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("load_calls", load_calls)
    g.add_node("classify_batch", classify_batch)
    g.add_node("classification_review_gate", classification_review_gate)
    g.add_node("analyze_topics", analyze_topics)
    g.add_node("detect_risks", detect_risks)
    g.add_node("risk_review_gate", risk_review_gate)
    g.add_node("write_all_insights", write_all_insights)
    g.add_node("persist_insights", persist_insights)

    g.add_edge(START, "load_calls")
    g.add_edge("load_calls", "classify_batch")
    g.add_edge("classify_batch", "classification_review_gate")
    g.add_edge("classification_review_gate", "analyze_topics")
    g.add_edge("analyze_topics", "detect_risks")
    g.add_edge("detect_risks", "risk_review_gate")
    g.add_edge("risk_review_gate", "write_all_insights")
    g.add_edge("write_all_insights", "persist_insights")
    g.add_edge("persist_insights", END)

    return g


def make_batch_id(tenant_id: str) -> str:
    return hashlib.sha256(f"batch:{tenant_id}".encode()).hexdigest()[:16]


def make_thread_config(batch_id: str) -> dict:
    return {"configurable": {"thread_id": batch_id}}


def _db_uri() -> str:
    return settings.database_url_sync.replace("+asyncpg", "")


async def run_pipeline(tenant_id: str, batch_id: str) -> dict[str, Any]:
    """
    Run (or resume) the pipeline for a tenant.
    Raises PipelineInterrupted if the graph pauses at a HITL gate.
    Returns final state dict on successful completion.
    """
    thread_config = make_thread_config(batch_id)

    async with AsyncPostgresSaver.from_conn_string(_db_uri()) as checkpointer:
        await checkpointer.setup()
        graph = _build_graph().compile(checkpointer=checkpointer)

        initial_state: PipelineState = {
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "calls_data": [],
            "classifications": [],
            "topics": [],
            "risks": [],
            "insights": [],
            "needs_review": [],
            "errors": [],
        }

        result = await graph.ainvoke(initial_state, config=thread_config)

        # Check if graph is paused at a HITL gate
        state = await graph.aget_state(thread_config)
        if state.next:
            pending_node = state.next[0]
            interrupt_data = []
            for task in state.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    for intr in task.interrupts:
                        interrupt_data.append(
                            intr.value if hasattr(intr, "value") else intr
                        )
            raise PipelineInterrupted(batch_id, pending_node, interrupt_data)

        return result


async def resume_pipeline(
    tenant_id: str,
    batch_id: str,
    resume_value: Any,
) -> dict[str, Any]:
    """Resume a graph that is paused at an interrupt() gate."""
    from langgraph.types import Command

    thread_config = make_thread_config(batch_id)

    async with AsyncPostgresSaver.from_conn_string(_db_uri()) as checkpointer:
        await checkpointer.setup()
        graph = _build_graph().compile(checkpointer=checkpointer)
        result = await graph.ainvoke(
            Command(resume=resume_value),
            config=thread_config,
        )

        # Check if still paused after resume (multi-gate flows)
        state = await graph.aget_state(thread_config)
        if state.next:
            pending_node = state.next[0]
            interrupt_data = []
            for task in state.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    for intr in task.interrupts:
                        interrupt_data.append(
                            intr.value if hasattr(intr, "value") else intr
                        )
            raise PipelineInterrupted(batch_id, pending_node, interrupt_data)

        return result


async def get_pipeline_state(batch_id: str) -> dict:
    """Return current state + pending interrupt data for a batch."""
    thread_config = make_thread_config(batch_id)

    async with AsyncPostgresSaver.from_conn_string(_db_uri()) as checkpointer:
        await checkpointer.setup()
        graph = _build_graph().compile(checkpointer=checkpointer)
        state = await graph.aget_state(thread_config)

        interrupt_data = []
        for task in state.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                for intr in task.interrupts:
                    interrupt_data.append(
                        intr.value if hasattr(intr, "value") else intr
                    )

        return {
            "next": list(state.next),
            "interrupt_data": interrupt_data,
            "values": state.values,
        }
