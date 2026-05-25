# Phase 3: Sentiment Analysis (`src/sentiment.py`)

## 🎯 PURPOSE

Aggregate sentiment across multiple dimensions and surface interpretable trends. Use pre-computed sentiment from `summary.json` as ground truth; don't re-run sentiment analysis.

**Time budget:** 1.5 hours

---

## 📋 REQUIREMENTS

### What to compute

1. **Sentiment by call type** — Are support calls more negative than external?
2. **Sentiment by sub-theme** — Which themes drive negativity?
3. **Sentiment over time** — Is sentiment trending up or down?
4. **Sentiment vs. meeting characteristics** — Duration, participant count, action items
5. **Negative outliers** — Top 10 most negative meetings (with context)
6. **Positive outliers** — Top 10 most positive meetings (with context)
7. **Per-sentence sentiment within transcripts** — Mood swings, escalation patterns

### Pre-computed fields to leverage

- `sentiment_score` (1-5 numeric) — from summary.json
- `overall_sentiment` (categorical: positive, neutral, negative, mixed-*) — from summary.json
- `transcript.json` data array has `sentimentType` per sentence (use sparingly — only for deep dives)

### Output

- A dict of structured findings (saved to `outputs/insights_report.json`)
- Plotly charts (saved to `outputs/charts/`)
- Text-form interpretations for the slides

---

## 💻 CODE TEMPLATE

```python
"""
Sentiment analysis module for Transcript Intelligence.

Builds on pre-computed sentiment scores from summary.json. Does NOT re-run
sentiment analysis (waste of compute — it's already there).

Focuses on aggregation, trend detection, and interpretation.

Design rationale:
- Functions are tool-shaped: parameters in, structured dict out
- Each function answers ONE question (foundation for agent tools)
- Results include provenance (meeting IDs) for evidence

Usage:
    from src.sentiment import (
        sentiment_by_call_type,
        sentiment_over_time,
        find_negative_outliers,
    )
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go


OUTPUT_DIR = Path("outputs")
CHARTS_DIR = OUTPUT_DIR / "charts"


# ============================================================================
# Aggregation functions (each is "tool-shaped")
# ============================================================================

def sentiment_by_call_type(df: pd.DataFrame) -> dict[str, Any]:
    """
    Aggregate sentiment statistics by call type.
    
    Args:
        df: Categorized meetings DataFrame
    
    Returns:
        {
            "by_call_type": {
                "support": {"mean": 2.8, "median": 3.0, "std": 0.7, "count": 35},
                "external": {...},
                "internal": {...}
            },
            "insight": "Support calls average X, external average Y..."
        }
    """
    stats = df.groupby("call_type")["sentiment_score"].agg(
        ["mean", "median", "std", "count", "min", "max"]
    ).round(2)
    
    result = {
        "by_call_type": stats.to_dict(orient="index"),
        "insight": _interpret_call_type_sentiment(stats),
    }
    return result


def _interpret_call_type_sentiment(stats: pd.DataFrame) -> str:
    """Generate a human-readable interpretation of call-type sentiment."""
    means = stats["mean"]
    most_negative = means.idxmin()
    most_positive = means.idxmax()
    spread = means.max() - means.min()
    
    return (
        f"{most_positive.title()} calls are the most positive (mean {means[most_positive]}); "
        f"{most_negative} calls are the most negative (mean {means[most_negative]}). "
        f"The gap of {spread:.1f} points is "
        f"{'large' if spread > 1.0 else 'moderate' if spread > 0.5 else 'small'}."
    )


def sentiment_by_sub_theme(df: pd.DataFrame) -> dict[str, Any]:
    """
    Aggregate sentiment by sub-theme to find which topics drive negativity.
    
    Returns:
        Stats per sub-theme + the top-3 most negative themes with meeting examples.
    """
    stats = df.groupby("sub_theme")["sentiment_score"].agg(
        ["mean", "count"]
    ).round(2).sort_values("mean")
    
    # Get top-3 negative themes (with at least 3 meetings)
    significant = stats[stats["count"] >= 3]
    top_negative = significant.head(3)
    
    examples = {}
    for theme in top_negative.index:
        examples[theme] = (
            df[df["sub_theme"] == theme]
            .nsmallest(2, "sentiment_score")[["meeting_id", "title", "sentiment_score"]]
            .to_dict(orient="records")
        )
    
    return {
        "by_sub_theme": stats.to_dict(orient="index"),
        "top_negative_themes": top_negative.to_dict(orient="index"),
        "examples": examples,
        "insight": (
            f"The most negative sub-themes are: " 
            + ", ".join([f"{t} ({stats.loc[t, 'mean']})" for t in top_negative.index])
            + ". These are leading indicators of business pain."
        ),
    }


def sentiment_over_time(df: pd.DataFrame, freq: str = "W") -> dict[str, Any]:
    """
    Compute sentiment trend over time.
    
    Args:
        df: Categorized meetings DataFrame
        freq: Pandas resample frequency. 'W' = weekly, 'M' = monthly
    
    Returns:
        Time series data + trend interpretation
    """
    ts = (
        df.set_index("start_time")
        .groupby([pd.Grouper(freq=freq), "call_type"])["sentiment_score"]
        .agg(["mean", "count"])
        .reset_index()
    )
    
    # Compute overall trend slope (simple linear regression)
    overall = df.set_index("start_time")["sentiment_score"].resample(freq).mean().dropna()
    if len(overall) >= 2:
        x = np.arange(len(overall))
        slope, intercept = np.polyfit(x, overall.values, 1)
        trend_direction = "improving" if slope > 0.05 else "declining" if slope < -0.05 else "flat"
    else:
        slope = 0
        trend_direction = "insufficient data"
    
    return {
        "series": ts.to_dict(orient="records"),
        "trend_slope": round(float(slope), 3),
        "trend_direction": trend_direction,
        "insight": (
            f"Overall sentiment is {trend_direction} over the analyzed period "
            f"(slope: {slope:+.3f} per {freq.lower()})."
        ),
    }


def sentiment_vs_characteristics(df: pd.DataFrame) -> dict[str, Any]:
    """
    Correlate sentiment with meeting characteristics: duration, participants, action items.
    
    Returns:
        Correlation coefficients + interpretation.
    """
    corrs = {
        "duration_min": df["sentiment_score"].corr(df["duration_min"]),
        "participant_count": df["sentiment_score"].corr(df["participant_count"]),
        "action_item_count": df["sentiment_score"].corr(df["action_item_count"]),
        "topic_count": df["sentiment_score"].corr(df["topic_count"]),
    }
    
    # Most influential
    strongest = max(corrs.items(), key=lambda kv: abs(kv[1]))
    
    return {
        "correlations": {k: round(float(v), 3) for k, v in corrs.items()},
        "strongest_correlation": {
            "variable": strongest[0],
            "value": round(float(strongest[1]), 3),
        },
        "insight": (
            f"{strongest[0]} has the strongest correlation with sentiment ({strongest[1]:+.2f}). "
            + (
                f"More {strongest[0].replace('_', ' ')} = "
                f"{'higher' if strongest[1] > 0 else 'lower'} sentiment."
            )
        ),
    }


def find_negative_outliers(df: pd.DataFrame, top_n: int = 10) -> list[dict]:
    """
    Find the most negative meetings, with context for understanding why.
    
    Args:
        df: Categorized meetings DataFrame
        top_n: How many to return
    
    Returns:
        List of dicts with meeting details and context.
    """
    negative = df.nsmallest(top_n, "sentiment_score")
    
    results = []
    for _, row in negative.iterrows():
        results.append({
            "meeting_id": row["meeting_id"],
            "title": row["title"],
            "call_type": row["call_type"],
            "sub_theme": row["sub_theme"],
            "sentiment_score": float(row["sentiment_score"]),
            "overall_sentiment": row["overall_sentiment"],
            "has_churn_signal": bool(row["has_churn_signal"]),
            "has_concern": bool(row["has_concern"]),
            "key_moment_count": int(row["key_moment_count"]),
            "summary_excerpt": (row["summary"] or "")[:200] + "...",
        })
    return results


def find_positive_outliers(df: pd.DataFrame, top_n: int = 10) -> list[dict]:
    """Find the most positive meetings (e.g., big wins, successful renewals)."""
    positive = df.nlargest(top_n, "sentiment_score")
    
    results = []
    for _, row in positive.iterrows():
        results.append({
            "meeting_id": row["meeting_id"],
            "title": row["title"],
            "call_type": row["call_type"],
            "sub_theme": row["sub_theme"],
            "sentiment_score": float(row["sentiment_score"]),
            "has_positive_pivot": bool(row["has_positive_pivot"]),
            "summary_excerpt": (row["summary"] or "")[:200] + "...",
        })
    return results


# ============================================================================
# Chart generation
# ============================================================================

def chart_sentiment_by_call_type(df: pd.DataFrame, save: bool = True) -> go.Figure:
    """Box plot of sentiment by call type."""
    fig = px.box(
        df,
        x="call_type",
        y="sentiment_score",
        color="call_type",
        title="Sentiment Distribution by Call Type",
        labels={"sentiment_score": "Sentiment Score (1-5)", "call_type": "Call Type"},
        points="outliers",
    )
    fig.update_layout(showlegend=False, height=450)
    
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "sentiment_by_call_type.html")
        try:
            fig.write_image(CHARTS_DIR / "sentiment_by_call_type.png")
        except Exception:
            pass  # kaleido not installed, skip PNG
    return fig


def chart_sentiment_over_time(df: pd.DataFrame, save: bool = True) -> go.Figure:
    """Line chart of weekly sentiment averages by call type."""
    ts = (
        df.set_index("start_time")
        .groupby([pd.Grouper(freq="W"), "call_type"])["sentiment_score"]
        .mean()
        .reset_index()
    )
    
    fig = px.line(
        ts,
        x="start_time",
        y="sentiment_score",
        color="call_type",
        title="Sentiment Trend Over Time (Weekly Average)",
        labels={"sentiment_score": "Avg Sentiment", "start_time": "Week"},
        markers=True,
    )
    fig.update_layout(height=450)
    
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "sentiment_over_time.html")
        try:
            fig.write_image(CHARTS_DIR / "sentiment_over_time.png")
        except Exception:
            pass
    return fig


def chart_sentiment_heatmap(df: pd.DataFrame, save: bool = True) -> go.Figure:
    """Heatmap of sentiment by call_type × sub_theme."""
    pivot = df.pivot_table(
        index="sub_theme",
        columns="call_type",
        values="sentiment_score",
        aggfunc="mean",
    )
    
    fig = px.imshow(
        pivot,
        text_auto=".2f",
        color_continuous_scale="RdYlGn",
        range_color=[1, 5],
        title="Average Sentiment: Sub-Theme × Call Type",
        labels={"color": "Sentiment"},
        aspect="auto",
    )
    fig.update_layout(height=500)
    
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "sentiment_heatmap.html")
        try:
            fig.write_image(CHARTS_DIR / "sentiment_heatmap.png")
        except Exception:
            pass
    return fig


# ============================================================================
# Master report generator
# ============================================================================

def generate_sentiment_report(df: pd.DataFrame) -> dict:
    """
    Generate the complete sentiment analysis report.
    
    Args:
        df: Categorized meetings DataFrame
    
    Returns:
        Full report dict (also saved to outputs/insights_report.json)
    """
    print("📊 Generating sentiment report...")
    
    report = {
        "by_call_type": sentiment_by_call_type(df),
        "by_sub_theme": sentiment_by_sub_theme(df),
        "over_time": sentiment_over_time(df),
        "vs_characteristics": sentiment_vs_characteristics(df),
        "negative_outliers": find_negative_outliers(df),
        "positive_outliers": find_positive_outliers(df),
    }
    
    # Generate charts
    chart_sentiment_by_call_type(df)
    chart_sentiment_over_time(df)
    chart_sentiment_heatmap(df)
    
    # Save report
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "sentiment_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    print("✅ Sentiment report saved to outputs/sentiment_report.json")
    print("✅ Charts saved to outputs/charts/")
    
    # Print key findings
    print(f"\n🔑 Key findings:")
    print(f"  • {report['by_call_type']['insight']}")
    print(f"  • {report['by_sub_theme']['insight']}")
    print(f"  • {report['over_time']['insight']}")
    print(f"  • {report['vs_characteristics']['insight']}")
    
    return report


if __name__ == "__main__":
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    df = load_meetings()
    df = categorize_meetings(df)
    generate_sentiment_report(df)
```

---

## ✅ ACCEPTANCE CRITERIA

1. ✅ Report runs end-to-end without errors
2. ✅ All 3 charts generated and saved as HTML
3. ✅ At least 4 distinct insights generated (one per aggregation function)
4. ✅ Each insight has an interpretation, not just numbers
5. ✅ Negative outliers list looks plausible (titles match "issue/outage/escalation" themes)

---

## 🎤 Q&A PREP

**"Why didn't you re-run sentiment analysis with a different model?"**
> "The pre-computed scores from summary.json are good enough — they're already in the data. Re-running would cost $30+ and likely produce similar results. The right work here is aggregation and interpretation, not regenerating signals."

**"What if the pre-computed sentiment is wrong?"**
> "Good question. I'd validate by sampling: take 20 random meetings, manually score them, compare to pre-computed. If they correlate well, trust them. If not, re-score. I'd build that into a sentiment eval suite for production. For this scope, I trusted the upstream pipeline."

**"How did you get insights, not just numbers?"**
> "Each aggregation function returns both raw stats AND a written interpretation. The interpretation is generated from the numbers but written in business terms — what's the largest gap, what's the trend direction, etc. This is the layer between 'data' and 'decisions'."
