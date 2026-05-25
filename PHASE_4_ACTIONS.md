# Phase 4B: Action Item Tracker (`src/action_tracker.py`)

## 🎯 PURPOSE

**Bonus Insight #2** — Extract, parse, and analyze action items across all 100 meetings.

**Why this matters:** Engineering leads, project managers, and chiefs of staff need to know:
- Who has the heaviest action item load?
- What action items keep recurring (= systemic issues)?
- Are certain meeting types better at producing actionable outcomes?

**Time budget:** 1.5 hours

---

## 📋 REQUIREMENTS

### Input format

Action items come from `summary.json` as strings in the format:
```
"Name: action description by [optional deadline]"
```

Examples:
- `"Megan Lawson: Draft updated customer communication explaining the phased rollout and revised timeline within the hour"`
- `"Raj Kapoor: Deliver internal retroactive event analysis summary report by Wednesday"`

### What to extract

For each action item, parse:
- **Owner** (name before the colon)
- **Action** (the verb+description)
- **Deadline** (parse "by X", "within Y", etc. if present)
- **Source meeting** (provenance)
- **Action category** (verb-based: communicate, deliver, prepare, investigate, schedule, etc.)

### What to analyze

1. **Owner workload** — Who has the most action items?
2. **Action verbs** — What are people being asked to do most? (communicate? deliver? investigate?)
3. **Recurring themes** — Action items mentioning the same topics across meetings (e.g., 5 meetings have actions about "documentation")
4. **Cross-meeting persistence** — Are people getting the same kind of action over and over? (= signal of unresolved issue)
5. **Action density per meeting** — Which meetings produce action vs. just discussion?

---

## 💻 CODE TEMPLATE

```python
"""
Action Item Tracker for Transcript Intelligence.

Extracts action items from meetings, attributes ownership, and surfaces
patterns: who is overloaded, what's recurring, what's systemic.

Design rationale:
- Pure pandas + regex (no LLM needed — format is consistent)
- Tool-shaped functions, each answers one question
- Output includes provenance (meeting IDs)

Usage:
    from src.action_tracker import (
        extract_all_action_items,
        owner_workload,
        recurring_action_themes,
    )
"""

import re
from pathlib import Path
from collections import Counter
import json
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


OUTPUT_DIR = Path("outputs")
CHARTS_DIR = OUTPUT_DIR / "charts"


# ============================================================================
# Parsing
# ============================================================================

# Format observed: "Name: action by deadline"
_OWNER_PATTERN = re.compile(r"^([^:]+):\s*(.+)$")

# Common action verbs (first word usually)
_ACTION_VERBS = {
    "draft", "send", "deliver", "prepare", "schedule", "review", "investigate",
    "communicate", "update", "create", "build", "deploy", "test", "validate",
    "document", "share", "publish", "submit", "follow", "coordinate", "set",
    "complete", "finalize", "discuss", "confirm", "check",
}

# Deadline keyword patterns
_DEADLINE_PATTERNS = [
    re.compile(r"by\s+(end of (?:day|week|month|quarter)|tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next \w+)", re.I),
    re.compile(r"within\s+(\w+\s+\w+)", re.I),
    re.compile(r"by\s+(\d{1,2}[:/\-]\d{1,2}(?:[:/\-]\d{2,4})?)", re.I),
]


def parse_action_item(item: str, meeting_id: str = "", meeting_title: str = "") -> dict[str, Any]:
    """
    Parse a single action item string into structured fields.
    
    Args:
        item: Action item string
        meeting_id: For provenance
        meeting_title: For context
    
    Returns:
        {
            "raw": "Megan Lawson: Draft updated customer communication...",
            "owner": "Megan Lawson",
            "action": "Draft updated customer communication...",
            "verb": "draft",
            "deadline": "within the hour",
            "has_deadline": True,
            "meeting_id": "...",
            "meeting_title": "...",
        }
    """
    item = (item or "").strip()
    
    owner = None
    action = item
    
    match = _OWNER_PATTERN.match(item)
    if match:
        owner = match.group(1).strip()
        action = match.group(2).strip()
    
    # Extract verb (first word, lowercased)
    verb = None
    if action:
        first = action.split()[0].lower().strip(".,;:")
        if first in _ACTION_VERBS:
            verb = first
        else:
            verb = first  # Capture even unknown verbs for visibility
    
    # Extract deadline
    deadline = None
    for pattern in _DEADLINE_PATTERNS:
        m = pattern.search(action)
        if m:
            deadline = m.group(0)
            break
    
    return {
        "raw": item,
        "owner": owner,
        "action": action,
        "verb": verb,
        "deadline": deadline,
        "has_deadline": deadline is not None,
        "meeting_id": meeting_id,
        "meeting_title": meeting_title,
    }


def extract_all_action_items(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract and parse all action items from all meetings.
    
    Args:
        df: Loaded meetings DataFrame (must have 'action_items', 'meeting_id', 'title' columns)
    
    Returns:
        DataFrame with one row per action item.
    """
    rows = []
    for _, meeting in df.iterrows():
        for item in (meeting["action_items"] or []):
            parsed = parse_action_item(item, meeting["meeting_id"], meeting["title"])
            parsed["meeting_call_type"] = meeting.get("call_type")
            parsed["meeting_sub_theme"] = meeting.get("sub_theme")
            parsed["meeting_date"] = meeting.get("start_time")
            rows.append(parsed)
    
    items_df = pd.DataFrame(rows)
    
    # Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    items_df.to_csv(OUTPUT_DIR / "action_items.csv", index=False)
    print(f"✅ Extracted {len(items_df)} action items from {len(df)} meetings")
    print(f"   Saved to outputs/action_items.csv")
    
    return items_df


# ============================================================================
# Analysis functions (tool-shaped)
# ============================================================================

def owner_workload(items_df: pd.DataFrame, top_n: int = 15) -> dict[str, Any]:
    """
    Compute per-owner action item counts.
    
    Args:
        items_df: Output of extract_all_action_items
        top_n: Top N to highlight
    
    Returns:
        {
            "rankings": [{"owner": "...", "count": ..., "meeting_count": ...}, ...],
            "top_loaded": "...",
            "insight": "..."
        }
    """
    # Drop owner-less items (parsing failures)
    df = items_df.dropna(subset=["owner"]).copy()
    
    by_owner = df.groupby("owner").agg(
        action_count=("action", "count"),
        meeting_count=("meeting_id", "nunique"),
        deadline_count=("has_deadline", "sum"),
    ).reset_index()
    
    by_owner["deadline_pct"] = (by_owner["deadline_count"] / by_owner["action_count"] * 100).round(0)
    by_owner = by_owner.sort_values("action_count", ascending=False)
    
    rankings = by_owner.head(top_n).to_dict(orient="records")
    
    top_loaded = rankings[0]["owner"] if rankings else "N/A"
    top_count = rankings[0]["action_count"] if rankings else 0
    
    return {
        "rankings": rankings,
        "top_loaded": top_loaded,
        "top_loaded_count": int(top_count),
        "total_owners": int(df["owner"].nunique()),
        "insight": (
            f"{top_loaded} has the most action items ({top_count}) across "
            f"{rankings[0]['meeting_count'] if rankings else 0} meetings. "
            f"This person may be a bottleneck or could need delegation support."
        ) if rankings else "No action items found.",
    }


def action_verb_distribution(items_df: pd.DataFrame) -> dict[str, Any]:
    """
    What verbs dominate? Reveals what the org spends time on (deliverables vs. communication vs. investigation).
    """
    verbs = items_df["verb"].dropna()
    counts = verbs.value_counts().head(15)
    
    return {
        "verb_counts": counts.to_dict(),
        "top_verb": counts.index[0] if len(counts) > 0 else "N/A",
        "insight": (
            f"The most common action verb is '{counts.index[0]}' ({counts.iloc[0]} times). "
            f"This reveals the org's primary working mode."
        ) if len(counts) > 0 else "No verbs extracted.",
    }


def recurring_action_themes(items_df: pd.DataFrame, top_keywords: int = 10) -> dict[str, Any]:
    """
    Find keywords that appear in action items across many DIFFERENT meetings.
    
    Recurring themes = potential systemic issues.
    
    e.g., If "documentation" appears in 8 meetings' action items, documentation
    is a recurring gap.
    """
    # Stop words to filter
    stop_words = {
        "the", "a", "an", "and", "or", "by", "to", "of", "in", "for", "on",
        "at", "from", "with", "within", "next", "this", "that", "be", "is",
        "are", "was", "were", "will", "would", "should", "could", "have",
        "has", "had", "her", "his", "their", "its", "our", "us", "we",
    }
    
    # Tokenize action strings
    keyword_meetings = {}  # keyword -> set of meeting_ids
    
    for _, item in items_df.iterrows():
        action = item.get("action", "") or ""
        meeting_id = item.get("meeting_id")
        if not meeting_id:
            continue
        
        words = re.findall(r"\b[a-zA-Z]{4,}\b", action.lower())
        for word in set(words):  # Use set to count per-action only once
            if word in stop_words:
                continue
            keyword_meetings.setdefault(word, set()).add(meeting_id)
    
    # Filter to keywords appearing in 3+ different meetings
    significant = {
        kw: len(meetings)
        for kw, meetings in keyword_meetings.items()
        if len(meetings) >= 3
    }
    
    top = sorted(significant.items(), key=lambda kv: -kv[1])[:top_keywords]
    
    examples = {}
    for kw, _ in top[:5]:
        mtg_ids = list(keyword_meetings[kw])[:3]
        examples[kw] = [
            items_df[items_df["meeting_id"] == mid].iloc[0]["meeting_title"]
            for mid in mtg_ids
            if not items_df[items_df["meeting_id"] == mid].empty
        ]
    
    return {
        "recurring_keywords": dict(top),
        "examples": examples,
        "insight": (
            f"The most recurring action-item themes are: "
            + ", ".join([f"'{kw}' ({count} meetings)" for kw, count in top[:3]])
            + ". Recurring themes may indicate unresolved systemic issues."
        ) if top else "No recurring themes detected.",
    }


def action_density_per_meeting(df: pd.DataFrame) -> dict[str, Any]:
    """
    Which meeting types are most action-productive?
    
    Average action items per meeting, by call_type and sub_theme.
    """
    by_type = df.groupby("call_type")["action_item_count"].agg(["mean", "sum", "count"]).round(2)
    by_theme = df.groupby("sub_theme")["action_item_count"].agg(["mean", "sum"]).round(2).sort_values("mean", ascending=False)
    
    return {
        "by_call_type": by_type.to_dict(orient="index"),
        "by_sub_theme": by_theme.to_dict(orient="index"),
        "insight": (
            f"{by_type['mean'].idxmax()} meetings produce the most actions per meeting "
            f"(avg {by_type['mean'].max():.1f}); "
            f"{by_type['mean'].idxmin()} produce the least ({by_type['mean'].min():.1f})."
        ),
    }


# ============================================================================
# Charts
# ============================================================================

def chart_owner_workload(workload_data: dict, top_n: int = 15, save: bool = True) -> go.Figure:
    """Horizontal bar chart of action items per owner."""
    rankings = workload_data["rankings"][:top_n]
    df_chart = pd.DataFrame(rankings)
    
    fig = px.bar(
        df_chart,
        x="action_count",
        y="owner",
        orientation="h",
        title=f"Top {top_n} Action Item Owners",
        labels={"action_count": "Action Item Count", "owner": ""},
        hover_data=["meeting_count", "deadline_pct"],
        color="action_count",
        color_continuous_scale="Blues",
    )
    fig.update_layout(
        height=max(400, 30 * top_n),
        yaxis={"categoryorder": "total ascending"},
        showlegend=False,
    )
    
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "owner_workload.html")
        try:
            fig.write_image(CHARTS_DIR / "owner_workload.png")
        except Exception:
            pass
    return fig


def chart_recurring_themes(themes_data: dict, save: bool = True) -> go.Figure:
    """Bar chart of recurring action-item keywords."""
    themes = themes_data["recurring_keywords"]
    if not themes:
        return go.Figure()
    
    df_chart = pd.DataFrame(
        [{"keyword": k, "meetings": v} for k, v in themes.items()]
    ).sort_values("meetings")
    
    fig = px.bar(
        df_chart,
        x="meetings",
        y="keyword",
        orientation="h",
        title="Recurring Action-Item Themes (across distinct meetings)",
        labels={"meetings": "Distinct Meetings Mentioning", "keyword": ""},
        color="meetings",
        color_continuous_scale="Reds",
    )
    fig.update_layout(height=max(400, 30 * len(themes)), showlegend=False)
    
    if save:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.write_html(CHARTS_DIR / "recurring_themes.html")
        try:
            fig.write_image(CHARTS_DIR / "recurring_themes.png")
        except Exception:
            pass
    return fig


# ============================================================================
# Master report
# ============================================================================

def generate_action_items_report(df: pd.DataFrame) -> dict:
    """Generate the complete action items analysis."""
    items_df = extract_all_action_items(df)
    
    report = {
        "total_action_items": len(items_df),
        "owners_with_actions": int(items_df["owner"].nunique()),
        "owner_workload": owner_workload(items_df),
        "verb_distribution": action_verb_distribution(items_df),
        "recurring_themes": recurring_action_themes(items_df),
        "action_density": action_density_per_meeting(df),
    }
    
    # Generate charts
    chart_owner_workload(report["owner_workload"])
    chart_recurring_themes(report["recurring_themes"])
    
    # Save
    with open(OUTPUT_DIR / "action_items_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    # Print insights
    print(f"\n🔑 Action item insights:")
    print(f"  • {report['owner_workload']['insight']}")
    print(f"  • {report['verb_distribution']['insight']}")
    print(f"  • {report['recurring_themes']['insight']}")
    print(f"  • {report['action_density']['insight']}")
    
    return report


if __name__ == "__main__":
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    df = load_meetings()
    df = categorize_meetings(df)
    generate_action_items_report(df)
```

---

## ✅ ACCEPTANCE CRITERIA

1. ✅ Owner extracted for >90% of action items (parsing works)
2. ✅ At least 3 recurring themes identified (keywords across 3+ meetings)
3. ✅ Top 5 owners list is plausible (not all the same person, not all CEO, etc.)
4. ✅ Both charts render

---

## 🎤 Q&A PREP

**"Why regex instead of LLM for parsing?"**
> "The format is consistent — 'Name: action by deadline'. Regex handles it for free. LLM here would be overkill and introduce variance. I save the LLM budget for tasks that genuinely need semantic understanding (categorization)."

**"How would you make this richer?"**
> "Two next steps: (1) Cross-reference owners with internal HR data to detect overload signals; (2) Track action item completion — link follow-up meetings to determine which items closed and which became recurring. That requires meeting threading, which is a separate problem."
