"""Shared fixtures: a real-data pipeline DataFrame and small synthetic builders."""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture(scope="session")
def real_df() -> pd.DataFrame:
    """The full 100-meeting corpus run through the offline pipeline once per session."""
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    from src.transcript_sentiment import add_transcript_features
    from src.churn_scorer import add_account_column

    df = load_meetings(save_csv=False)
    df = categorize_meetings(df, use_llm=False)
    df = add_transcript_features(df)
    df = add_account_column(df)
    return df


def make_turns(sentiments, role="customer"):
    """Build a list of transcript turns from a sequence of sentiment labels."""
    value = {"negative": 1.0, "neutral": 3.0, "positive": 5.0}
    return [
        {"speaker_id": 0, "speaker": f"{role.title()} Person", "role": role,
         "sentiment_type": s, "sentiment_value": value[s], "time": float(i)}
        for i, s in enumerate(sentiments)
    ]


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    """A tiny hand-built DataFrame exercising churn / topic / journey logic."""
    rows = [
        {
            "meeting_id": "m1", "title": "Aegis / Acme Corp - Renewal", "call_type": "external",
            "sub_theme": "customer_renewal", "account": "Acme Corp",
            "start_time": pd.Timestamp("2026-01-05", tz="UTC"), "sentiment_score": 4.0,
            "topics": ["renewal", "pricing"], "action_item_count": 2,
            "key_moments": [{"type": "positive_pivot", "text": "happy", "speaker": "x"}],
            "late_customer_sentiment": 4.0, "has_negative_pivot": False,
        },
        {
            "meeting_id": "m2", "title": "Aegis / Acme Corp - Escalation", "call_type": "external",
            "sub_theme": "incident_response", "account": "Acme Corp",
            "start_time": pd.Timestamp("2026-02-05", tz="UTC"), "sentiment_score": 2.5,
            "topics": ["outage", "sla breach"], "action_item_count": 4,
            "key_moments": [{"type": "concern", "text": "worried", "speaker": "y"}],
            "late_customer_sentiment": 2.5, "has_negative_pivot": True,
        },
        {
            "meeting_id": "m3", "title": "Support Case #1 - Acme Corp Outage", "call_type": "support",
            "sub_theme": "customer_support_issue", "account": "Acme Corp",
            "start_time": pd.Timestamp("2026-03-05", tz="UTC"), "sentiment_score": 1.5,
            "topics": ["outage", "churn risk"], "action_item_count": 1,
            "key_moments": [
                {"type": "churn_signal", "text": "considering leaving", "speaker": "z"},
                {"type": "concern", "text": "frustrated", "speaker": "z"},
            ],
            "late_customer_sentiment": 1.5, "has_negative_pivot": True,
        },
        {
            "meeting_id": "m4", "title": "Aegis / Globex - QBR", "call_type": "external",
            "sub_theme": "customer_renewal", "account": "Globex",
            "start_time": pd.Timestamp("2026-02-10", tz="UTC"), "sentiment_score": 4.5,
            "topics": ["renewal", "expansion"], "action_item_count": 1,
            "key_moments": [],
            "late_customer_sentiment": 4.5, "has_negative_pivot": False,
        },
    ]
    return pd.DataFrame(rows)
