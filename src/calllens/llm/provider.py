"""
LLM factory — swap provider with one env var.

If LANGFUSE_PUBLIC_KEY is set, every LLM call is automatically traced
in Langfuse under the trace_name passed via tags.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from calllens.config import settings


def _langfuse_callback(trace_name: str = "calllens", metadata: dict | None = None):
    """Return a LangFuse CallbackHandler, or None if Langfuse is not configured."""
    if not settings.langfuse_public_key:
        return None
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            trace_name=trace_name,
            metadata=metadata or {},
        )
    except ImportError:
        return None


def get_llm(
    temperature: float | None = None,
    trace_name: str = "calllens",
    metadata: dict | None = None,
) -> BaseChatModel:
    t = temperature if temperature is not None else settings.llm_temperature

    callbacks = []
    cb = _langfuse_callback(trace_name=trace_name, metadata=metadata)
    if cb:
        callbacks.append(cb)

    kwargs: dict = {"callbacks": callbacks} if callbacks else {}

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.llm_model,
            temperature=t,
            api_key=settings.anthropic_api_key,
            **kwargs,
        )

    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.llm_model,
        temperature=t,
        api_key=settings.openai_api_key,
        **kwargs,
    )
