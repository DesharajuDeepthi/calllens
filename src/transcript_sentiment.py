from __future__ import annotations
"""
Transcript-level sentiment analysis for Transcript Intelligence.

The meeting-level `sentimentScore` in summary.json is a single pre-computed
scalar. transcript.json, however, carries a sentiment label AND a speaker for
every sentence. This module mines that richer signal:

- Rep vs. customer sentiment (who is actually unhappy on a call?)
- Intra-meeting sentiment arc (did the call end worse than it started?)
- Per-speaker sentiment (which individuals drive negativity)
- A transcript-derived meeting score, used to validate the pre-computed one.

Usage:
    from src.transcript_sentiment import add_transcript_features, generate_transcript_report
    df = add_transcript_features(df)
    report = generate_transcript_report(df)
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


OUTPUT_DIR = Path("outputs")
CHARTS_DIR = OUTPUT_DIR / "charts"

# A late-call drop of at least this many points (on the 1-5 scale) is a "negative pivot".
PIVOT_THRESHOLD = 0.5


def _values(turns: list[dict], role: str | None = None) -> list[float]:
    """Sentiment values from turns, optionally filtered to a single role."""
    return [
        float(t["sentiment_value"])
        for t in (turns or [])
        if t.get("sentiment_value") is not None
        and (role is None or t.get("role") == role)
    ]


def derived_meeting_sentiment(turns: list[dict]) -> float | None:
    """Mean per-sentence sentiment for a meeting (1-5), or None if no turns."""
    vals = _values(turns)
    return round(float(np.mean(vals)), 3) if vals else None


def role_sentiment(turns: list[dict]) -> dict[str, Any]:
    """Split sentiment by speaker role (rep vs. customer)."""
    cust = _values(turns, "customer")
    rep = _values(turns, "rep")
    cust_mean = round(float(np.mean(cust)), 3) if cust else None
    rep_mean = round(float(np.mean(rep)), 3) if rep else None
    gap = round(rep_mean - cust_mean, 3) if (cust_mean is not None and rep_mean is not None) else None
    cust_neg_share = (
        round(sum(1 for v in cust if v < 3.0) / len(cust), 3) if cust else None
    )
    return {
        "customer_sentiment": cust_mean,
        "rep_sentiment": rep_mean,
        "rep_minus_customer": gap,
        "customer_negative_share": cust_neg_share,
        "customer_turns": len(cust),
        "rep_turns": len(rep),
    }


def meeting_sentiment_arc(turns: list[dict], role: str | None = None) -> dict[str, Any]:
    """
    Sentiment trajectory across a meeting, split into thirds.

    Returns the first/middle/last-third means, an overall slope (points across
    the meeting), and whether the call ended materially worse than it started.
    """
    vals = _values(turns, role)
    n = len(vals)
    if n < 3:
        return {"start": None, "middle": None, "end": None, "slope": None,
                "has_negative_pivot": False, "n_turns": n}

    third = n // 3
    start = float(np.mean(vals[:third]))
    middle = float(np.mean(vals[third:2 * third]))
    end = float(np.mean(vals[2 * third:]))

    x = np.linspace(0.0, 1.0, n)
    slope = float(np.polyfit(x, vals, 1)[0])

    return {
        "start": round(start, 3),
        "middle": round(middle, 3),
        "end": round(end, 3),
        "slope": round(slope, 3),
        "has_negative_pivot": bool(end < start - PIVOT_THRESHOLD),
        "n_turns": n,
    }


def late_call_sentiment(turns: list[dict], role: str | None = None) -> float | None:
    """Mean sentiment over the final third of a call (optionally one role)."""
    vals = _values(turns, role)
    if len(vals) < 3:
        return round(float(np.mean(vals)), 3) if vals else None
    return round(float(np.mean(vals[2 * (len(vals) // 3):])), 3)


def speaker_sentiment(turns: list[dict], min_turns: int = 3) -> dict[str, Any]:
    """Per-speaker mean sentiment; surfaces the most negative speaker."""
    by_speaker: dict[str, list[float]] = {}
    roles: dict[str, str] = {}
    for t in (turns or []):
        name = t.get("speaker") or "Unknown"
        by_speaker.setdefault(name, []).append(float(t["sentiment_value"]))
        roles[name] = t.get("role", "unknown")

    rows = [
        {"speaker": name, "role": roles[name], "mean_sentiment": round(float(np.mean(v)), 3),
         "turns": len(v)}
        for name, v in by_speaker.items()
        if len(v) >= min_turns
    ]
    rows.sort(key=lambda r: r["mean_sentiment"])
    return {
        "by_speaker": rows,
        "most_negative_speaker": rows[0]["speaker"] if rows else None,
    }


def add_transcript_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add transcript-derived sentiment columns to the meetings DataFrame."""
    if "transcript_turns" not in df.columns:
        raise KeyError(
            "DataFrame has no 'transcript_turns' column. "
            "Load with the updated src.loader.load_meetings()."
        )

    df = df.copy()
    arcs = df["transcript_turns"].apply(meeting_sentiment_arc)
    roles = df["transcript_turns"].apply(role_sentiment)

    df["derived_sentiment"] = df["transcript_turns"].apply(derived_meeting_sentiment)
    df["customer_sentiment"] = roles.apply(lambda r: r["customer_sentiment"])
    df["rep_sentiment"] = roles.apply(lambda r: r["rep_sentiment"])
    df["sentiment_arc_slope"] = arcs.apply(lambda a: a["slope"])
    df["has_negative_pivot"] = arcs.apply(lambda a: a["has_negative_pivot"])
    df["late_customer_sentiment"] = df["transcript_turns"].apply(
        lambda t: late_call_sentiment(t, role="customer")
    )
    df["most_negative_speaker"] = df["transcript_turns"].apply(
        lambda t: speaker_sentiment(t)["most_negative_speaker"]
    )
    return df


# ============================================================================
# Charts
# ============================================================================

def chart_rep_vs_customer(df: pd.DataFrame, save: bool = True) -> go.Figure:
    """Scatter of rep vs. customer sentiment for customer-facing meetings."""
    cols = {"rep_sentiment", "customer_sentiment"}
    if not cols.issubset(df.columns):
        return go.Figure()
    sub = df.dropna(subset=["rep_sentiment", "customer_sentiment"]).copy()
    if sub.empty:
        return go.Figure()

    fig = px.scatter(
        sub, x="rep_sentiment", y="customer_sentiment",
        color="call_type" if "call_type" in sub.columns else None,
        hover_data=["title"] if "title" in sub.columns else None,
        title="Rep vs. Customer Sentiment (per meeting)",
        labels={"rep_sentiment": "Rep sentiment (1-5)",
                "customer_sentiment": "Customer sentiment (1-5)"},
        range_x=[1, 5], range_y=[1, 5],
    )
    fig.add_shape(type="line", x0=1, y0=1, x1=5, y1=5,
                  line=dict(dash="dash", color="grey"))
    fig.update_layout(height=500)
    _save(fig, "rep_vs_customer_sentiment", save)
    return fig


def chart_negative_pivots(df: pd.DataFrame, save: bool = True) -> go.Figure:
    """Bar of how many meetings end materially worse than they start, by call type."""
    if "has_negative_pivot" not in df.columns:
        return go.Figure()
    grp = (
        df.groupby("call_type")["has_negative_pivot"].mean().mul(100).round(1)
        .reset_index() if "call_type" in df.columns
        else pd.DataFrame({"call_type": ["all"],
                           "has_negative_pivot": [df["has_negative_pivot"].mean() * 100]})
    )
    fig = px.bar(
        grp, x="call_type", y="has_negative_pivot",
        title="Share of Meetings Ending Worse Than They Started",
        labels={"has_negative_pivot": "% with negative pivot", "call_type": "Call type"},
        color="call_type",
    )
    fig.update_layout(showlegend=False, height=400)
    _save(fig, "negative_pivots", save)
    return fig


def _save(fig: go.Figure, name: str, save: bool) -> None:
    if not save:
        return
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.write_html(CHARTS_DIR / f"{name}.html")
    try:
        fig.write_image(CHARTS_DIR / f"{name}.png")
    except Exception:
        pass


# ============================================================================
# Master report
# ============================================================================

def generate_transcript_report(df: pd.DataFrame) -> dict:
    """Generate the transcript-level sentiment report and charts."""
    if "derived_sentiment" not in df.columns:
        df = add_transcript_features(df)

    pivots = int(df["has_negative_pivot"].sum())
    cust = df["customer_sentiment"].dropna()
    rep = df["rep_sentiment"].dropna()

    gap = None
    if not cust.empty and not rep.empty:
        gap = round(float(rep.mean() - cust.mean()), 2)

    report = {
        "meetings_analyzed": int(df["transcript_turns"].apply(bool).sum()),
        "negative_pivots": pivots,
        "negative_pivot_share": round(pivots / len(df), 3) if len(df) else 0.0,
        "avg_customer_sentiment": round(float(cust.mean()), 2) if not cust.empty else None,
        "avg_rep_sentiment": round(float(rep.mean()), 2) if not rep.empty else None,
        "rep_minus_customer_gap": gap,
        "most_negative_customers": (
            df.dropna(subset=["customer_sentiment"])
            .nsmallest(5, "customer_sentiment")[["meeting_id", "title", "customer_sentiment"]]
            .to_dict(orient="records")
        ),
        "insight": (
            f"Reps read {gap:+.2f} points more positive than customers on the same calls — "
            "the aggregate score masks customer frustration."
            if gap is not None else
            "No customer-facing transcripts with both rep and customer turns."
        ),
    }

    chart_rep_vs_customer(df)
    chart_negative_pivots(df)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "transcript_sentiment_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    print("✅ Transcript sentiment report saved to outputs/transcript_sentiment_report.json")
    print(f"  • {report['insight']}")
    print(f"  • {pivots} meetings ended materially worse than they started.")
    return report


if __name__ == "__main__":
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    df = load_meetings()
    df = categorize_meetings(df, use_llm=False)
    df = add_transcript_features(df)
    generate_transcript_report(df)
