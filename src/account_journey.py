from __future__ import annotations
"""
Cross-meeting account journeys for Transcript Intelligence.

The churn scorer treats an account as a bag of meetings. But a customer with
three calls trending down is a very different risk from one with a single bad
call. This module reconstructs each account's meeting *sequence* over time and
classifies its sentiment trajectory — a signal the churn scorer consumes.

Usage:
    from src.account_journey import build_all_journeys, generate_journey_report
    journeys = build_all_journeys(df)
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

DECLINE_SLOPE = -0.3   # points/meeting steeper than this => "declining"
IMPROVE_SLOPE = 0.3


def _trajectory(scores: list[float]) -> dict[str, Any]:
    """Classify a sentiment sequence as declining / improving / volatile / stable."""
    n = len(scores)
    if n < 2:
        return {"slope": 0.0, "label": "single_point", "volatility": 0.0}

    x = np.arange(n)
    slope = float(np.polyfit(x, scores, 1)[0])
    volatility = float(np.std(scores))

    if volatility > 1.0 and abs(slope) < IMPROVE_SLOPE:
        label = "volatile"
    elif slope <= DECLINE_SLOPE:
        label = "declining"
    elif slope >= IMPROVE_SLOPE:
        label = "improving"
    else:
        label = "stable"

    return {"slope": round(slope, 3), "label": label, "volatility": round(volatility, 3)}


def build_account_journey(df: pd.DataFrame, account: str) -> dict[str, Any]:
    """Reconstruct one account's ordered meeting history and trajectory."""
    rows = df[df["account"] == account].dropna(subset=["start_time"]).sort_values("start_time")
    if rows.empty:
        return {"account": account, "meeting_count": 0, "trajectory": _trajectory([])}

    scores = rows["sentiment_score"].astype(float).tolist()
    dates = pd.to_datetime(rows["start_time"])
    cadence_days = (
        round(float(dates.diff().dropna().dt.days.mean()), 1)
        if len(dates) > 1 else None
    )

    timeline = [
        {"meeting_id": r["meeting_id"], "title": r["title"],
         "date": str(pd.to_datetime(r["start_time"]).date()),
         "sentiment_score": float(r["sentiment_score"]),
         "call_type": r.get("call_type")}
        for _, r in rows.iterrows()
    ]

    return {
        "account": account,
        "meeting_count": len(rows),
        "first_meeting": timeline[0]["date"],
        "last_meeting": timeline[-1]["date"],
        "avg_cadence_days": cadence_days,
        "trajectory": _trajectory(scores),
        "first_sentiment": scores[0],
        "last_sentiment": scores[-1],
        "timeline": timeline,
    }


def build_all_journeys(df: pd.DataFrame, min_meetings: int = 2) -> list[dict]:
    """Build journeys for every multi-meeting account, declining trajectories first."""
    if "account" not in df.columns:
        from src.churn_scorer import add_account_column
        df = add_account_column(df)

    accounts = df["account"].dropna().unique()
    journeys = [build_account_journey(df, a) for a in accounts]
    journeys = [j for j in journeys if j["meeting_count"] >= min_meetings]

    order = {"declining": 0, "volatile": 1, "stable": 2, "improving": 3, "single_point": 4}
    journeys.sort(key=lambda j: (order.get(j["trajectory"]["label"], 9), j["trajectory"]["slope"]))

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "account_journeys.json", "w") as f:
        json.dump(journeys, f, indent=2, default=str)
    return journeys


def trajectory_lookup(journeys: list[dict]) -> dict[str, dict]:
    """account -> trajectory dict, for the churn scorer to consume."""
    return {j["account"]: j["trajectory"] for j in journeys}


def chart_account_trajectories(journeys: list[dict], top_n: int = 6, save: bool = True) -> go.Figure:
    """Line chart of sentiment over time for the most at-risk (declining) accounts."""
    declining = [j for j in journeys if j["trajectory"]["label"] in ("declining", "volatile")][:top_n]
    if not declining:
        return go.Figure()

    rows = [
        {"account": j["account"], "date": pt["date"], "sentiment_score": pt["sentiment_score"]}
        for j in declining for pt in j["timeline"]
    ]
    fig = px.line(
        pd.DataFrame(rows), x="date", y="sentiment_score", color="account",
        markers=True, title="At-Risk Account Sentiment Trajectories",
        labels={"sentiment_score": "Meeting sentiment (1-5)", "date": "Meeting date"},
        range_y=[1, 5],
    )
    fig.update_layout(height=500)
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "account_trajectories.html")
        try:
            fig.write_image(CHARTS_DIR / "account_trajectories.png")
        except Exception:
            pass
    return fig


def generate_journey_report(df: pd.DataFrame) -> dict:
    """Build journeys, chart trajectories, and summarise."""
    journeys = build_all_journeys(df)
    labels = pd.Series([j["trajectory"]["label"] for j in journeys]).value_counts().to_dict()
    declining = [j["account"] for j in journeys if j["trajectory"]["label"] == "declining"]

    report = {
        "accounts_with_history": len(journeys),
        "trajectory_distribution": labels,
        "declining_accounts": declining,
        "insight": (
            f"{len(declining)} accounts show a declining sentiment trajectory across "
            f"multiple meetings: {', '.join(declining[:5]) or 'none'}. "
            "A downward arc is a stronger churn signal than any single bad call."
        ),
    }

    chart_account_trajectories(journeys)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "account_journey_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("✅ Account journey report saved to outputs/account_journey_report.json")
    print(f"  • {report['insight']}")
    return report


if __name__ == "__main__":
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    from src.churn_scorer import add_account_column
    df = load_meetings()
    df = categorize_meetings(df, use_llm=False)
    df = add_account_column(df)
    generate_journey_report(df)
