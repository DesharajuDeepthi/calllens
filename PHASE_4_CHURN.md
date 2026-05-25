# Phase 4A: Churn Risk Scorer (`src/churn_scorer.py`)

## 🎯 PURPOSE

**Bonus Insight #1** — Rank customer accounts by churn risk based on transcript signals.

This is the **most impressive bonus insight** because it connects transcripts to revenue. Sales and CS leaders care about this directly.

**Time budget:** 2 hours

---

## 📋 REQUIREMENTS

### Inputs
- Categorized meetings DataFrame from Phase 2
- Focus on `call_type == 'external'` (customer-facing calls)

### What constitutes "churn risk"

A weighted combination of:
1. **`churn_signal` key moments** (explicit signals: dissatisfaction, threats to leave, vocal complaints)
2. **Negative sentiment trend** (sentiment dropping across multiple meetings for same customer)
3. **`concern` key moments** (worries expressed in meeting)
4. **Recent low-sentiment meetings** (very recent bad calls)
5. **Multiple support cases referenced** (signals systemic issues)

### How to identify "the customer" in each external meeting

External meetings have titles like "Aegis / Redwood Clinical - ISO 27001 Preparation". Parse out the customer name (everything after `/` and before `-`).

### Output

A ranked list of accounts with:
- Account name
- Risk score (0-100)
- Component scores (churn signals, sentiment, concerns)
- Evidence (specific meeting IDs + quotes)
- Recommendation (Watch, Alert, Critical)

---

## 💻 CODE TEMPLATE

```python
"""
Churn Risk Scorer for Transcript Intelligence.

Scores customer accounts by churn risk using transcript signals.
This is a heuristic scorer — not a trained ML model. The advantage is
transparency: every score is explainable and inspectable.

Design rationale:
- Tool-shaped: takes filters, returns ranked dict with evidence
- Transparent scoring (weighted sum of components)
- Returns citations (meeting IDs + quotes) so users can verify

Production note: With labeled data (which customers actually churned),
this would become a trained classifier (logistic regression / gradient
boosted trees). The signals identified here would be the feature set.

Usage:
    from src.churn_scorer import score_all_accounts, get_account_detail
    rankings = score_all_accounts(df)
    detail = get_account_detail(df, "Redwood Clinical")
"""

import re
from typing import Any
from pathlib import Path
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


OUTPUT_DIR = Path("outputs")
CHARTS_DIR = OUTPUT_DIR / "charts"


# ============================================================================
# Account name extraction
# ============================================================================

_TITLE_PATTERNS = [
    # "Aegis / Customer Name - Purpose"
    re.compile(r"^\w+\s*/\s*(.+?)\s*[-–]\s*", re.I),
    # "Support Case #1234 - Customer Name Billing Inquiry"
    re.compile(r"support case\s*#?\d+\s*[-–]\s*(.+?)\s+(?:billing|inquiry|issue|case)", re.I),
]


def extract_account_name(title: str) -> str | None:
    """
    Extract customer/account name from a meeting title.
    
    Examples:
        "Aegis / Redwood Clinical - ISO 27001 Preparation" → "Redwood Clinical"
        "Support Case #9279 - Summit Trust Billing Inquiry" → "Summit Trust"
    
    Returns:
        Customer name string, or None if can't extract.
    """
    if not title:
        return None
    
    for pattern in _TITLE_PATTERNS:
        match = pattern.search(title)
        if match:
            return match.group(1).strip()
    
    return None


def add_account_column(df: pd.DataFrame) -> pd.DataFrame:
    """Add an 'account' column to the DataFrame by extracting from titles."""
    df = df.copy()
    df["account"] = df["title"].apply(extract_account_name)
    return df


# ============================================================================
# Scoring components
# ============================================================================

def _churn_signal_score(meetings: pd.DataFrame) -> float:
    """
    Score based on count of churn_signal key moments.
    
    Each churn signal counts as 25 points, capped at 50.
    """
    total_signals = sum(
        1
        for moments in meetings["key_moments"]
        for km in (moments or [])
        if km.get("type") == "churn_signal"
    )
    return min(total_signals * 25, 50)


def _sentiment_score(meetings: pd.DataFrame) -> float:
    """
    Score based on sentiment.
    
    - Average sentiment < 2.5: +30 points
    - Average sentiment < 3.0: +15 points
    - Declining trend (recent meetings worse than older): +10 points
    """
    if len(meetings) == 0:
        return 0
    
    avg = meetings["sentiment_score"].mean()
    points = 0
    
    if avg < 2.5:
        points += 30
    elif avg < 3.0:
        points += 15
    elif avg < 3.5:
        points += 5
    
    # Trend (compare first half vs second half if multiple meetings)
    if len(meetings) >= 3:
        sorted_m = meetings.sort_values("start_time")
        mid = len(sorted_m) // 2
        early = sorted_m.iloc[:mid]["sentiment_score"].mean()
        late = sorted_m.iloc[mid:]["sentiment_score"].mean()
        if late < early - 0.5:  # Sentiment dropping
            points += 10
    
    return min(points, 40)


def _concern_score(meetings: pd.DataFrame) -> float:
    """
    Score based on concerns raised. Each concern = 5 points, capped at 20.
    """
    total = sum(
        1
        for moments in meetings["key_moments"]
        for km in (moments or [])
        if km.get("type") == "concern"
    )
    return min(total * 5, 20)


def _recent_negativity_score(meetings: pd.DataFrame) -> float:
    """
    Score for very recent negative meetings.
    
    Most recent meeting having sentiment < 2.5 = +15 points
    Most recent meeting having sentiment < 3.0 = +5 points
    """
    if len(meetings) == 0:
        return 0
    
    most_recent = meetings.sort_values("start_time").iloc[-1]
    if most_recent["sentiment_score"] < 2.5:
        return 15
    elif most_recent["sentiment_score"] < 3.0:
        return 5
    return 0


# ============================================================================
# Main scoring function (tool-shaped)
# ============================================================================

def score_account(df: pd.DataFrame, account: str) -> dict[str, Any]:
    """
    Score a single account for churn risk.
    
    Args:
        df: Full categorized meetings DataFrame (with 'account' column)
        account: Account name to score
    
    Returns:
        {
            "account": "Redwood Clinical",
            "risk_score": 67.0,
            "risk_level": "Alert",
            "meeting_count": 3,
            "components": {
                "churn_signals": 25,
                "sentiment": 30,
                "concerns": 10,
                "recent_negativity": 5,
            },
            "evidence": [
                {"meeting_id": "...", "title": "...", "quote": "..."}
            ],
            "recommendation": "..."
        }
    """
    account_meetings = df[df["account"] == account].copy()
    
    if len(account_meetings) == 0:
        return {
            "account": account,
            "risk_score": 0,
            "risk_level": "Unknown",
            "meeting_count": 0,
            "components": {},
            "evidence": [],
            "recommendation": "No meetings found for this account.",
        }
    
    # Compute components
    churn_pts = _churn_signal_score(account_meetings)
    sent_pts = _sentiment_score(account_meetings)
    concern_pts = _concern_score(account_meetings)
    recent_pts = _recent_negativity_score(account_meetings)
    
    total = churn_pts + sent_pts + concern_pts + recent_pts
    
    # Risk level
    if total >= 70:
        risk_level = "Critical"
        recommendation = "Immediate executive outreach. High likelihood of churn."
    elif total >= 50:
        risk_level = "Alert"
        recommendation = "Schedule check-in within 1 week. Multiple warning signs."
    elif total >= 30:
        risk_level = "Watch"
        recommendation = "Monitor closely. Some negative signals present."
    else:
        risk_level = "Healthy"
        recommendation = "No immediate action needed."
    
    # Collect evidence (top 5 most concerning quotes)
    evidence = []
    for _, row in account_meetings.iterrows():
        for km in (row["key_moments"] or []):
            if km.get("type") in ("churn_signal", "concern"):
                evidence.append({
                    "meeting_id": row["meeting_id"],
                    "title": row["title"],
                    "type": km.get("type"),
                    "quote": km.get("text", "")[:200],
                    "speaker": km.get("speaker", ""),
                    "sentiment_score": float(row["sentiment_score"]),
                })
    
    # Sort: churn_signal first, then by sentiment
    evidence.sort(key=lambda e: (e["type"] != "churn_signal", e["sentiment_score"]))
    evidence = evidence[:5]
    
    return {
        "account": account,
        "risk_score": round(total, 1),
        "risk_level": risk_level,
        "meeting_count": int(len(account_meetings)),
        "avg_sentiment": round(float(account_meetings["sentiment_score"].mean()), 2),
        "most_recent_meeting": account_meetings.sort_values("start_time").iloc[-1]["start_time"].strftime("%Y-%m-%d"),
        "components": {
            "churn_signals": churn_pts,
            "sentiment": sent_pts,
            "concerns": concern_pts,
            "recent_negativity": recent_pts,
        },
        "evidence": evidence,
        "recommendation": recommendation,
    }


def score_all_accounts(df: pd.DataFrame, min_meetings: int = 1) -> list[dict]:
    """
    Score every customer account in the dataset.
    
    Args:
        df: Categorized meetings DataFrame
        min_meetings: Filter to accounts with at least N meetings
    
    Returns:
        List of account scores, sorted descending by risk_score.
    """
    # Add account column if not present
    if "account" not in df.columns:
        df = add_account_column(df)
    
    # Focus on external + support meetings (customer-facing)
    customer_facing = df[df["call_type"].isin(["external", "support"])].copy()
    
    accounts = customer_facing["account"].dropna().unique()
    
    print(f"🔍 Scoring {len(accounts)} accounts for churn risk...")
    
    results = []
    for account in accounts:
        score = score_account(customer_facing, account)
        if score["meeting_count"] >= min_meetings:
            results.append(score)
    
    # Sort by risk score descending
    results.sort(key=lambda x: x["risk_score"], reverse=True)
    
    # Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "churn_rankings.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"✅ Saved rankings to outputs/churn_rankings.json")
    
    # Print summary
    risk_dist = pd.Series([r["risk_level"] for r in results]).value_counts()
    print(f"\n📊 Risk distribution:")
    for level, count in risk_dist.items():
        print(f"   {level}: {count}")
    
    print(f"\n🚨 Top 5 highest-risk accounts:")
    for r in results[:5]:
        print(f"   [{r['risk_score']:.0f}] {r['account']} ({r['risk_level']}) — {r['meeting_count']} meetings")
    
    return results


# ============================================================================
# Visualization
# ============================================================================

def chart_top_risk_accounts(rankings: list[dict], top_n: int = 15, save: bool = True) -> go.Figure:
    """Horizontal bar chart of top N highest-risk accounts."""
    top = rankings[:top_n]
    
    df_chart = pd.DataFrame([
        {
            "account": r["account"],
            "risk_score": r["risk_score"],
            "risk_level": r["risk_level"],
            "meeting_count": r["meeting_count"],
        }
        for r in top
    ])
    
    color_map = {"Critical": "#d62728", "Alert": "#ff7f0e", "Watch": "#ffbb78", "Healthy": "#2ca02c"}
    
    fig = px.bar(
        df_chart,
        x="risk_score",
        y="account",
        orientation="h",
        color="risk_level",
        color_discrete_map=color_map,
        title=f"Top {top_n} Accounts by Churn Risk",
        labels={"risk_score": "Churn Risk Score (0-100)", "account": ""},
        hover_data=["meeting_count"],
    )
    fig.update_layout(
        height=max(400, 30 * top_n),
        yaxis={"categoryorder": "total ascending"},
    )
    
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "churn_risk_top.html")
        try:
            fig.write_image(CHARTS_DIR / "churn_risk_top.png")
        except Exception:
            pass
    return fig


def chart_risk_components(rankings: list[dict], top_n: int = 10, save: bool = True) -> go.Figure:
    """Stacked bar showing what drives each top account's risk."""
    top = rankings[:top_n]
    
    component_data = []
    for r in top:
        for comp, value in r["components"].items():
            component_data.append({
                "account": r["account"],
                "component": comp,
                "score": value,
            })
    
    df_comp = pd.DataFrame(component_data)
    
    fig = px.bar(
        df_comp,
        x="score",
        y="account",
        color="component",
        orientation="h",
        title=f"Risk Score Components — Top {top_n} Accounts",
        labels={"score": "Component Score", "account": ""},
    )
    fig.update_layout(height=max(400, 35 * top_n))
    
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "churn_risk_components.html")
        try:
            fig.write_image(CHARTS_DIR / "churn_risk_components.png")
        except Exception:
            pass
    return fig


if __name__ == "__main__":
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    df = load_meetings()
    df = categorize_meetings(df)
    df = add_account_column(df)
    rankings = score_all_accounts(df)
    chart_top_risk_accounts(rankings)
    chart_risk_components(rankings)
```

---

## ✅ ACCEPTANCE CRITERIA

1. ✅ Account name extraction works for >80% of external/support meetings
2. ✅ Rankings file has at least 10 accounts scored
3. ✅ Top-ranked accounts make qualitative sense (have churn signals OR low sentiment OR concerns)
4. ✅ Evidence is concrete (real quotes from real meetings)
5. ✅ Distribution across Critical/Alert/Watch/Healthy is not degenerate

---

## 🎤 Q&A PREP

**"Is this ML?"**
> "No — it's a transparent heuristic with weighted scoring. The advantage is explainability: every score has component breakdown and evidence. The disadvantage is the weights are my judgment. With labeled data (who actually churned), I'd train a classifier and the signals here become the feature set."

**"How would you validate this?"**
> "Two ways. (1) Backtest: take historical data, score accounts, see if high-risk ones actually churned. (2) Run a side-by-side experiment: CS team uses this list for 1 quarter, measure outreach effectiveness vs. their usual prioritization."

**"What about false positives — accounts that look risky but are fine?"**
> "Real concern. That's why I include evidence — the CS rep reviews the cited quotes before action. The tool ranks, the human decides. For production, I'd add a feedback loop: when a flagged account turns out healthy, log that as training signal."
