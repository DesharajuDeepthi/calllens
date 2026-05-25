# Phase 4C: Recurring Topic Analyzer (`src/topic_analyzer.py`)

## 🎯 PURPOSE

**Bonus Insight #3** — Identify topics recurring across multiple meetings, their sentiment correlation, and lifecycle (when they appear, how often, with what mood).

**Why this matters:** Product managers and engineering leads want to know: *"What keeps coming up?"* If "outage" appears in 8 meetings over 2 weeks with declining sentiment, that's a major signal.

**Time budget:** 1.5 hours

---

## 📋 REQUIREMENTS

### What to compute

1. **Topic frequency** — Which topics appear in the most meetings?
2. **Topic-sentiment correlation** — Which topics drag sentiment down?
3. **Topic timeline** — When does each topic appear? Is it spreading?
4. **Co-occurring topics** — Which topics tend to appear together? (e.g., "outage" + "customer communication")
5. **Topic lifecycle** — Early-stage (new topic), recurring (stable), or escalating?

### Data source

Use the `topics` field from `summary.json` (already loaded into the DataFrame as a list per meeting).

### Output

- Ranked list of recurring topics with stats
- Topic-sentiment heatmap or scatter
- Topic timeline visualization
- Co-occurrence findings

---

## 💻 CODE TEMPLATE

```python
"""
Recurring Topic Analyzer for Transcript Intelligence.

Surfaces topics that appear across multiple meetings, correlates them with
sentiment, and visualizes their lifecycle. Built on pre-computed `topics`
field from summary.json.

Design rationale:
- Tool-shaped functions: filter parameters in, structured findings out
- Uses pre-computed topics (already-curated by upstream summarization)
- Provenance preserved (meeting IDs per topic)

Usage:
    from src.topic_analyzer import (
        topic_frequency,
        topic_sentiment_correlation,
        topic_timeline,
        topic_co_occurrence,
    )
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


# ============================================================================
# Frequency analysis
# ============================================================================

def topic_frequency(df: pd.DataFrame, min_count: int = 3) -> dict[str, Any]:
    """
    Find topics appearing in multiple meetings.
    
    Args:
        df: Loaded meetings DataFrame
        min_count: Minimum meeting count to be "recurring"
    
    Returns:
        {
            "all_topics": {topic: count, ...},
            "recurring": [{"topic": "...", "meeting_count": N, "meeting_ids": [...]}, ...],
            "unique_topics_count": N,
            "insight": "..."
        }
    """
    topic_meetings: dict[str, list[str]] = defaultdict(list)
    
    for _, row in df.iterrows():
        for topic in (row["topics"] or []):
            topic_meetings[topic].append(row["meeting_id"])
    
    all_counts = {t: len(mids) for t, mids in topic_meetings.items()}
    
    recurring = [
        {
            "topic": topic,
            "meeting_count": len(mids),
            "meeting_ids": mids,
        }
        for topic, mids in topic_meetings.items()
        if len(mids) >= min_count
    ]
    recurring.sort(key=lambda x: x["meeting_count"], reverse=True)
    
    top_recurring = recurring[:5]
    
    return {
        "all_topics": all_counts,
        "recurring": recurring,
        "unique_topics_count": len(all_counts),
        "recurring_count": len(recurring),
        "top_recurring": top_recurring,
        "insight": (
            f"{len(recurring)} topics appear in {min_count}+ meetings. "
            f"Most recurring: " 
            + ", ".join([f"'{t['topic']}' ({t['meeting_count']} meetings)" for t in top_recurring[:3]])
        ) if recurring else "No recurring topics found.",
    }


# ============================================================================
# Topic-sentiment correlation
# ============================================================================

def topic_sentiment_correlation(df: pd.DataFrame, min_count: int = 3) -> dict[str, Any]:
    """
    Find topics that correlate with negative or positive sentiment.
    
    Returns:
        Sorted list of topics with their avg sentiment in meetings that include them.
    """
    topic_data: dict[str, list[float]] = defaultdict(list)
    
    for _, row in df.iterrows():
        score = row["sentiment_score"]
        for topic in (row["topics"] or []):
            topic_data[topic].append(score)
    
    # Aggregate
    rows = []
    for topic, scores in topic_data.items():
        if len(scores) >= min_count:
            rows.append({
                "topic": topic,
                "meeting_count": len(scores),
                "mean_sentiment": round(np.mean(scores), 2),
                "min_sentiment": round(np.min(scores), 2),
                "max_sentiment": round(np.max(scores), 2),
            })
    
    rows.sort(key=lambda x: x["mean_sentiment"])
    
    # Identify negative drivers (lowest sentiment with significant meeting count)
    most_negative = rows[:5]
    most_positive = sorted(rows, key=lambda x: x["mean_sentiment"], reverse=True)[:5]
    
    return {
        "ranked": rows,
        "most_negative_topics": most_negative,
        "most_positive_topics": most_positive,
        "insight": (
            f"Topics most associated with negative sentiment: "
            + ", ".join([f"'{t['topic']}' ({t['mean_sentiment']})" for t in most_negative[:3]])
            + ". These are leading indicators of where the org is hurting."
        ) if most_negative else "Insufficient data.",
    }


# ============================================================================
# Timeline analysis
# ============================================================================

def topic_timeline(df: pd.DataFrame, top_n: int = 10) -> dict[str, Any]:
    """
    Build a timeline of when topics appear.
    
    For the top-N recurring topics, return a time series of weekly occurrence counts.
    """
    # Get top recurring topics
    freq = topic_frequency(df, min_count=2)
    top_topics = [t["topic"] for t in freq["recurring"][:top_n]]
    
    timeline_data = []
    for _, row in df.iterrows():
        if row["start_time"] is None or pd.isna(row["start_time"]):
            continue
        for topic in (row["topics"] or []):
            if topic in top_topics:
                timeline_data.append({
                    "topic": topic,
                    "date": row["start_time"],
                    "meeting_id": row["meeting_id"],
                    "sentiment_score": row["sentiment_score"],
                })
    
    timeline_df = pd.DataFrame(timeline_data)
    
    if len(timeline_df) == 0:
        return {"timeline": [], "insight": "No timeline data available."}
    
    # Resample weekly per topic
    weekly = (
        timeline_df.set_index("date")
        .groupby([pd.Grouper(freq="W"), "topic"])
        .agg(
            occurrence_count=("meeting_id", "count"),
            avg_sentiment=("sentiment_score", "mean"),
        )
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

def topic_co_occurrence(df: pd.DataFrame, min_pairs: int = 3) -> dict[str, Any]:
    """
    Find topic pairs that frequently co-occur in the same meetings.
    
    Reveals what topics tend to come together (e.g., 'outage' + 'customer communication').
    
    Args:
        df: Loaded meetings DataFrame
        min_pairs: Minimum co-occurrences to be reported
    
    Returns:
        Ranked list of co-occurring topic pairs.
    """
    pair_counts: Counter = Counter()
    
    for _, row in df.iterrows():
        topics = sorted(set(row["topics"] or []))
        for pair in combinations(topics, 2):
            pair_counts[pair] += 1
    
    # Filter and sort
    significant = [
        {"topic_a": a, "topic_b": b, "co_occurrence_count": count}
        for (a, b), count in pair_counts.items()
        if count >= min_pairs
    ]
    significant.sort(key=lambda x: x["co_occurrence_count"], reverse=True)
    
    top_5 = significant[:5]
    
    return {
        "pairs": significant,
        "top_pairs": top_5,
        "insight": (
            f"The most co-occurring topic pairs are: "
            + "; ".join([f"'{p['topic_a']}' + '{p['topic_b']}' ({p['co_occurrence_count']})" for p in top_5[:3]])
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


def chart_topic_sentiment(corr_data: dict, top_n: int = 15, save: bool = True) -> go.Figure:
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
    fig.update_traces(textposition="top center", textfont_size=10)
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
    """Line chart: occurrence of top topics over time."""
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
    """Generate the complete topic analysis."""
    print("🔍 Analyzing topics...")
    
    report = {
        "frequency": topic_frequency(df),
        "sentiment_correlation": topic_sentiment_correlation(df),
        "timeline": topic_timeline(df),
        "co_occurrence": topic_co_occurrence(df),
    }
    
    # Charts
    chart_topic_frequency(report["frequency"])
    chart_topic_sentiment(report["sentiment_correlation"])
    chart_topic_timeline(report["timeline"])
    
    # Save
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
```

---

## ✅ ACCEPTANCE CRITERIA

1. ✅ At least 5 recurring topics identified (in 3+ meetings)
2. ✅ Sentiment correlation reveals clear negative drivers
3. ✅ Timeline chart shows topics appearing over time
4. ✅ At least 3 meaningful co-occurrence pairs found

---

## 🎤 Q&A PREP

**"Why use pre-computed topics instead of running LDA or BERTopic?"**
> "The upstream summarizer already curated topics per meeting — they're cleaner than what LDA would surface on a 100-doc corpus. Topic modeling shines when you have thousands of documents and want to discover latent themes. With 100 meetings and pre-curated topics, the right move is aggregation and correlation."

**"How would you scale this?"**
> "At 10k+ meetings, I'd add (1) topic clustering — merge near-synonyms like 'outage' and 'incident'; (2) embedding-based similarity for finding semantically related topics that don't share exact strings; (3) trend tests — is a topic accelerating, plateauing, or fading?"
