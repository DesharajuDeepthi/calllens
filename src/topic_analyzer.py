from __future__ import annotations
"""
Recurring Topic Analyzer for Transcript Intelligence.

Surfaces topics that appear across multiple meetings, correlates them with
sentiment, and visualizes their lifecycle. Built on pre-computed `topics`
field from summary.json.

Usage:
    from src.topic_analyzer import generate_topic_report
    report = generate_topic_report(df)
"""

import json
from pathlib import Path
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go


OUTPUT_DIR = Path("outputs")
CHARTS_DIR = OUTPUT_DIR / "charts"

import re

_TOPIC_PUNCT = re.compile(r"[^\w\s]")


def _normalize_topic(topic: str) -> frozenset:
    """Token set for a topic: lowercased, de-punctuated, naive singularisation."""
    cleaned = _TOPIC_PUNCT.sub(" ", (topic or "").lower())
    tokens = {
        (w[:-1] if len(w) > 3 and w.endswith("s") else w)
        for w in cleaned.split()
    }
    return frozenset(tokens)


def build_topic_canonical_map(topic_counts: dict[str, int], jaccard: float = 0.6) -> dict[str, str]:
    """
    Map near-duplicate topics to a single canonical label.

    "compliance" and "compliance reporting" both roll up to the most frequent
    of the group. Two topics merge when one token set contains the other, or
    their Jaccard overlap is high. Deterministic: more frequent topics win.
    """
    norm = {t: _normalize_topic(t) for t in topic_counts}
    ordered = sorted(topic_counts, key=lambda t: (-topic_counts[t], len(t)))

    canon: dict[str, str] = {}
    reps: list[tuple[str, frozenset]] = []
    for t in ordered:
        ts = norm[t]
        match = None
        for rep_topic, rep_ts in reps:
            if not ts or not rep_ts:
                continue
            overlap = len(ts & rep_ts) / len(ts | rep_ts)
            if ts <= rep_ts or rep_ts <= ts or overlap >= jaccard:
                match = rep_topic
                break
        if match:
            canon[t] = match
        else:
            canon[t] = t
            reps.append((t, ts))
    return canon


# ============================================================================
# Frequency analysis
# ============================================================================

def topic_frequency(df: pd.DataFrame, min_count: int = 3, canonicalize: bool = False) -> dict[str, Any]:
    """
    Find topics appearing in multiple meetings.

    With ``canonicalize=True``, near-duplicate topics are merged (their distinct
    meeting sets are unioned) before counting.
    """
    topic_meetings: dict[str, set[str]] = defaultdict(set)

    for _, row in df.iterrows():
        for topic in (row.get("topics") or []):
            topic_meetings[topic].add(row["meeting_id"])

    if canonicalize:
        raw_counts = {t: len(mids) for t, mids in topic_meetings.items()}
        cmap = build_topic_canonical_map(raw_counts)
        merged: dict[str, set[str]] = defaultdict(set)
        for topic, mids in topic_meetings.items():
            merged[cmap[topic]] |= mids
        topic_meetings = merged

    topic_meetings = {t: sorted(mids) for t, mids in topic_meetings.items()}
    all_counts = {t: len(mids) for t, mids in topic_meetings.items()}

    recurring = sorted(
        [
            {"topic": topic, "meeting_count": len(mids), "meeting_ids": mids}
            for topic, mids in topic_meetings.items()
            if len(mids) >= min_count
        ],
        key=lambda x: x["meeting_count"],
        reverse=True,
    )

    top_recurring = recurring[:5]

    return {
        "all_topics": all_counts,
        "recurring": recurring,
        "unique_topics_count": len(all_counts),
        "recurring_count": len(recurring),
        "top_recurring": top_recurring,
        "insight": (
            f"{len(recurring)} topics appear in {min_count}+ meetings. "
            "Most recurring: "
            + ", ".join([f"'{t['topic']}' ({t['meeting_count']} meetings)" for t in top_recurring[:3]])
        ) if recurring else "No recurring topics found.",
    }


# ============================================================================
# Topic-sentiment correlation
# ============================================================================

def topic_sentiment_correlation(df: pd.DataFrame, min_count: int = 3) -> dict[str, Any]:
    """Find topics that correlate with negative or positive sentiment."""
    topic_data: dict[str, list[float]] = defaultdict(list)

    for _, row in df.iterrows():
        score = row["sentiment_score"]
        for topic in (row.get("topics") or []):
            topic_data[topic].append(score)

    rows = [
        {
            "topic": topic,
            "meeting_count": len(scores),
            "mean_sentiment": round(float(np.mean(scores)), 2),
            "min_sentiment": round(float(np.min(scores)), 2),
            "max_sentiment": round(float(np.max(scores)), 2),
        }
        for topic, scores in topic_data.items()
        if len(scores) >= min_count
    ]
    rows.sort(key=lambda x: x["mean_sentiment"])

    most_negative = rows[:5]
    most_positive = sorted(rows, key=lambda x: x["mean_sentiment"], reverse=True)[:5]

    return {
        "ranked": rows,
        "most_negative_topics": most_negative,
        "most_positive_topics": most_positive,
        "insight": (
            "Topics most associated with negative sentiment: "
            + ", ".join([f"'{t['topic']}' ({t['mean_sentiment']})" for t in most_negative[:3]])
            + ". These are leading indicators of where the org is hurting."
        ) if most_negative else "Insufficient data.",
    }


# ============================================================================
# Timeline
# ============================================================================

def topic_timeline(df: pd.DataFrame, top_n: int = 10) -> dict[str, Any]:
    """Build a weekly timeline of occurrences for the top recurring topics."""
    freq = topic_frequency(df, min_count=2)
    top_topics = [t["topic"] for t in freq["recurring"][:top_n]]

    timeline_data = [
        {
            "topic": topic,
            "date": row["start_time"],
            "meeting_id": row["meeting_id"],
            "sentiment_score": row["sentiment_score"],
        }
        for _, row in df.iterrows()
        if row.get("start_time") is not None and not pd.isna(row["start_time"])
        for topic in (row.get("topics") or [])
        if topic in top_topics
    ]

    if not timeline_data:
        return {"timeline": [], "tracked_topics": top_topics, "insight": "No timeline data available."}

    timeline_df = pd.DataFrame(timeline_data)
    weekly = (
        timeline_df.set_index("date")
        .groupby([pd.Grouper(freq="W"), "topic"])
        .agg(occurrence_count=("meeting_id", "count"), avg_sentiment=("sentiment_score", "mean"))
        .reset_index()
    )

    return {
        "timeline": weekly.to_dict(orient="records"),
        "tracked_topics": top_topics,
        "insight": f"Tracking {len(top_topics)} recurring topics across the time period.",
    }


# ============================================================================
# Co-occurrence
# ============================================================================

def topic_co_occurrence(df: pd.DataFrame, min_pairs: int = 2) -> dict[str, Any]:
    """Find topic pairs that frequently co-occur in the same meetings."""
    pair_counts: Counter = Counter()

    for _, row in df.iterrows():
        topics = sorted(set(row.get("topics") or []))
        for pair in combinations(topics, 2):
            pair_counts[pair] += 1

    significant = sorted(
        [
            {"topic_a": a, "topic_b": b, "co_occurrence_count": count}
            for (a, b), count in pair_counts.items()
            if count >= min_pairs
        ],
        key=lambda x: x["co_occurrence_count"],
        reverse=True,
    )

    top_5 = significant[:5]

    return {
        "pairs": significant,
        "top_pairs": top_5,
        "insight": (
            "The most co-occurring topic pairs are: "
            + "; ".join([
                f"'{p['topic_a']}' + '{p['topic_b']}' ({p['co_occurrence_count']})"
                for p in top_5[:3]
            ])
        ) if top_5 else "No significant co-occurrences.",
    }


# ============================================================================
# Charts
# ============================================================================

def chart_topic_frequency(freq_data: dict, top_n: int = 15, save: bool = True) -> go.Figure:
    """Bar chart of most recurring topics."""
    top = freq_data["recurring"][:top_n]
    if not top:
        return go.Figure()

    df_chart = pd.DataFrame(top).sort_values("meeting_count")
    fig = px.bar(
        df_chart,
        x="meeting_count",
        y="topic",
        orientation="h",
        title=f"Most Recurring Topics (Top {top_n})",
        labels={"meeting_count": "Distinct Meetings", "topic": ""},
        color="meeting_count",
        color_continuous_scale="Viridis",
    )
    fig.update_layout(height=max(400, 30 * len(top)), showlegend=False)

    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "topic_frequency.html")
        try:
            fig.write_image(CHARTS_DIR / "topic_frequency.png")
        except Exception:
            pass
    return fig


def chart_topic_sentiment(corr_data: dict, top_n: int = 20, save: bool = True) -> go.Figure:
    """Scatter: topic frequency vs. avg sentiment."""
    ranked = corr_data["ranked"][:top_n]
    if not ranked:
        return go.Figure()

    df_chart = pd.DataFrame(ranked)
    fig = px.scatter(
        df_chart,
        x="meeting_count",
        y="mean_sentiment",
        text="topic",
        size="meeting_count",
        color="mean_sentiment",
        color_continuous_scale="RdYlGn",
        range_color=[1, 5],
        title="Topics: Frequency vs. Sentiment",
        labels={"meeting_count": "Meeting Count", "mean_sentiment": "Avg Sentiment"},
    )
    fig.update_traces(textposition="top center", textfont_size=9)
    fig.update_layout(height=600)

    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "topic_sentiment.html")
        try:
            fig.write_image(CHARTS_DIR / "topic_sentiment.png")
        except Exception:
            pass
    return fig


def chart_topic_timeline(timeline_data: dict, save: bool = True) -> go.Figure:
    """Line chart of topic occurrences over time."""
    timeline = timeline_data.get("timeline", [])
    if not timeline:
        return go.Figure()

    df_chart = pd.DataFrame(timeline)
    fig = px.line(
        df_chart,
        x="date",
        y="occurrence_count",
        color="topic",
        title="Topic Occurrences Over Time (Weekly)",
        labels={"occurrence_count": "Meetings Mentioning Topic", "date": "Week"},
        markers=True,
    )
    fig.update_layout(height=500)

    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "topic_timeline.html")
        try:
            fig.write_image(CHARTS_DIR / "topic_timeline.png")
        except Exception:
            pass
    return fig


# ============================================================================
# Master report
# ============================================================================

def generate_topic_report(df: pd.DataFrame) -> dict:
    """Generate the complete topic analysis report."""
    print("🔍 Analyzing topics...")

    report = {
        "frequency": topic_frequency(df),
        "sentiment_correlation": topic_sentiment_correlation(df),
        "timeline": topic_timeline(df),
        "co_occurrence": topic_co_occurrence(df),
    }

    chart_topic_frequency(report["frequency"])
    chart_topic_sentiment(report["sentiment_correlation"])
    chart_topic_timeline(report["timeline"])

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "topic_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n🔑 Topic insights:")
    print(f"  • {report['frequency']['insight']}")
    print(f"  • {report['sentiment_correlation']['insight']}")
    print(f"  • {report['co_occurrence']['insight']}")

    return report


if __name__ == "__main__":
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    df = load_meetings()
    df = categorize_meetings(df)
    generate_topic_report(df)
