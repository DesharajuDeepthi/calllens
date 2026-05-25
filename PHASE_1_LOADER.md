# Phase 1: Data Loader (`src/loader.py`)

## 🎯 PURPOSE

Load all 100 meetings from `data/dataset/` and produce a flat pandas DataFrame ready for analysis.

**Time budget:** 30 minutes (this is the easiest module)

---

## 📋 REQUIREMENTS

### Input
- Directory: `data/dataset/`
- 100 subdirectories, each named with a meeting ID (e.g., `01KQ03B0303900521BB089CA`)
- Each contains 6 JSON files (see CLAUDE.md for structure)

### Output
- A pandas DataFrame with one row per meeting
- Saved to `outputs/meetings_flat.csv`
- Object also returned for downstream use

### DataFrame Schema

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `meeting_id` | str | folder name | Unique meeting identifier |
| `title` | str | meeting-info.json | Meeting title |
| `organizer` | str | meeting-info.json | Email of organizer |
| `host` | str | meeting-info.json | Email of host |
| `start_time` | datetime | meeting-info.json | UTC start time |
| `end_time` | datetime | meeting-info.json | UTC end time |
| `duration_min` | float | meeting-info.json | Duration in minutes |
| `participant_count` | int | meeting-info.json | Number of allEmails |
| `participants` | list[str] | meeting-info.json | List of participant emails |
| `summary` | str | summary.json | Pre-computed summary text |
| `action_items` | list[str] | summary.json | List of action item strings |
| `action_item_count` | int | computed | len(action_items) |
| `topics` | list[str] | summary.json | Pre-computed topic strings |
| `topic_count` | int | computed | len(topics) |
| `overall_sentiment` | str | summary.json | e.g. "positive", "mixed-negative" |
| `sentiment_score` | float | summary.json | Numeric sentiment (1-5 scale) |
| `key_moments` | list[dict] | summary.json | Full list of key moment dicts |
| `key_moment_count` | int | computed | len(key_moments) |
| `key_moment_types` | list[str] | computed | Distinct `type` values in key_moments |
| `has_churn_signal` | bool | computed | Any key_moment with type='churn_signal' |
| `has_technical_issue` | bool | computed | Any key_moment with type='technical_issue' |
| `has_concern` | bool | computed | Any key_moment with type='concern' |
| `has_positive_pivot` | bool | computed | Any key_moment with type='positive_pivot' |
| `speakers` | list[str] | speaker-meta.json | Unique speaker names |
| `speaker_count` | int | computed | len(speakers) |
| `transcript_sentence_count` | int | transcript.json | Count of sentences in transcript |
| `transcript_text` | str | transcript.json | All sentences concatenated (for keyword search) |

---

## 💻 CODE TEMPLATE

```python
"""
Data loader for Transcript Intelligence.

Loads 100 meeting transcripts from data/dataset/ and produces a flat pandas
DataFrame for downstream analysis. Uses pre-computed fields from summary.json
where available (summary text, topics, sentiment, key moments).

Usage:
    from src.loader import load_meetings
    df = load_meetings()
"""

import json
from pathlib import Path
from typing import Any
from datetime import datetime

import pandas as pd
from tqdm import tqdm


DATA_DIR = Path("data/dataset")
OUTPUT_DIR = Path("outputs")


def _load_json(filepath: Path) -> dict | list:
    """Load a JSON file, returning empty dict/list on failure."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠️  Warning: Could not load {filepath}: {e}")
        return {}


def _parse_meeting(meeting_dir: Path) -> dict[str, Any]:
    """Parse a single meeting directory into a flat record."""
    meeting_id = meeting_dir.name
    
    # Load all JSON files
    info = _load_json(meeting_dir / "meeting-info.json")
    summary = _load_json(meeting_dir / "summary.json")
    speakers_meta = _load_json(meeting_dir / "speaker-meta.json")
    transcript = _load_json(meeting_dir / "transcript.json")
    
    # Extract key moments and derive flags
    key_moments = summary.get("keyMoments", []) or []
    key_moment_types = list({km.get("type", "") for km in key_moments if km.get("type")})
    
    has_churn = any(km.get("type") == "churn_signal" for km in key_moments)
    has_tech = any(km.get("type") == "technical_issue" for km in key_moments)
    has_concern = any(km.get("type") == "concern" for km in key_moments)
    has_positive = any(km.get("type") == "positive_pivot" for km in key_moments)
    
    # Speakers from speaker-meta.json (dict of id -> name)
    speakers = list(speakers_meta.values()) if isinstance(speakers_meta, dict) else []
    
    # Transcript sentences
    transcript_data = transcript.get("data", []) if isinstance(transcript, dict) else []
    sentences = [s.get("sentence", "") for s in transcript_data]
    full_text = " ".join(sentences)
    
    # Parse timestamps
    start_time = info.get("startTime")
    end_time = info.get("endTime")
    
    record = {
        "meeting_id": meeting_id,
        "title": info.get("title", ""),
        "organizer": info.get("organizerEmail", ""),
        "host": info.get("host", ""),
        "start_time": pd.to_datetime(start_time) if start_time else None,
        "end_time": pd.to_datetime(end_time) if end_time else None,
        "duration_min": info.get("duration", 0.0),
        "participant_count": len(info.get("allEmails", [])),
        "participants": info.get("allEmails", []),
        "summary": summary.get("summary", ""),
        "action_items": summary.get("actionItems", []) or [],
        "action_item_count": len(summary.get("actionItems", []) or []),
        "topics": summary.get("topics", []) or [],
        "topic_count": len(summary.get("topics", []) or []),
        "overall_sentiment": summary.get("overallSentiment", "unknown"),
        "sentiment_score": float(summary.get("sentimentScore", 3.0)),
        "key_moments": key_moments,
        "key_moment_count": len(key_moments),
        "key_moment_types": key_moment_types,
        "has_churn_signal": has_churn,
        "has_technical_issue": has_tech,
        "has_concern": has_concern,
        "has_positive_pivot": has_positive,
        "speakers": speakers,
        "speaker_count": len(speakers),
        "transcript_sentence_count": len(sentences),
        "transcript_text": full_text,
    }
    
    return record


def load_meetings(data_dir: Path = DATA_DIR, save_csv: bool = True) -> pd.DataFrame:
    """
    Load all meetings from the dataset directory.
    
    Args:
        data_dir: Path to dataset directory (default: data/dataset/)
        save_csv: Whether to save the flat DataFrame as CSV (default: True)
    
    Returns:
        pandas DataFrame with one row per meeting, with columns as documented
        in the schema. List/dict columns are kept as Python objects.
    """
    if not data_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {data_dir}")
    
    meeting_dirs = sorted([d for d in data_dir.iterdir() if d.is_dir()])
    
    if not meeting_dirs:
        raise ValueError(f"No meeting directories found in {data_dir}")
    
    print(f"📂 Loading {len(meeting_dirs)} meetings from {data_dir}...")
    
    records = []
    for meeting_dir in tqdm(meeting_dirs, desc="Loading"):
        try:
            record = _parse_meeting(meeting_dir)
            records.append(record)
        except Exception as e:
            print(f"⚠️  Failed to parse {meeting_dir.name}: {e}")
    
    df = pd.DataFrame(records)
    
    # Sort by start time for time-series analysis later
    df = df.sort_values("start_time").reset_index(drop=True)
    
    if save_csv:
        OUTPUT_DIR.mkdir(exist_ok=True)
        # Note: list/dict columns will be serialized as strings in CSV
        # That's OK for backup; in-memory we keep them as objects
        df_for_csv = df.copy()
        for col in ["participants", "action_items", "topics", "key_moments", 
                    "key_moment_types", "speakers"]:
            df_for_csv[col] = df_for_csv[col].apply(json.dumps)
        df_for_csv.to_csv(OUTPUT_DIR / "meetings_flat.csv", index=False)
        print(f"✅ Saved {len(df)} meetings to {OUTPUT_DIR / 'meetings_flat.csv'}")
    
    return df


def quick_stats(df: pd.DataFrame) -> dict:
    """
    Print and return quick summary statistics about the dataset.
    
    Args:
        df: Output of load_meetings()
    
    Returns:
        Dict of stats
    """
    stats = {
        "total_meetings": len(df),
        "date_range": (
            df["start_time"].min().strftime("%Y-%m-%d") if df["start_time"].notna().any() else "N/A",
            df["start_time"].max().strftime("%Y-%m-%d") if df["start_time"].notna().any() else "N/A",
        ),
        "total_duration_hours": round(df["duration_min"].sum() / 60, 1),
        "avg_duration_min": round(df["duration_min"].mean(), 1),
        "avg_participants": round(df["participant_count"].mean(), 1),
        "total_action_items": df["action_item_count"].sum(),
        "total_unique_speakers": len(set().union(*df["speakers"])),
        "sentiment_distribution": df["overall_sentiment"].value_counts().to_dict(),
        "meetings_with_churn_signal": int(df["has_churn_signal"].sum()),
        "meetings_with_technical_issue": int(df["has_technical_issue"].sum()),
        "meetings_with_concern": int(df["has_concern"].sum()),
        "meetings_with_positive_pivot": int(df["has_positive_pivot"].sum()),
    }
    
    print("\n📊 Dataset Quick Stats:")
    print(f"  Total meetings: {stats['total_meetings']}")
    print(f"  Date range: {stats['date_range'][0]} → {stats['date_range'][1]}")
    print(f"  Total duration: {stats['total_duration_hours']} hours")
    print(f"  Avg duration: {stats['avg_duration_min']} min")
    print(f"  Avg participants: {stats['avg_participants']}")
    print(f"  Total action items: {stats['total_action_items']}")
    print(f"  Unique speakers: {stats['total_unique_speakers']}")
    print(f"\n  Sentiment distribution:")
    for sent, count in stats["sentiment_distribution"].items():
        print(f"    {sent}: {count}")
    print(f"\n  Key moment flags:")
    print(f"    Churn signals: {stats['meetings_with_churn_signal']}")
    print(f"    Technical issues: {stats['meetings_with_technical_issue']}")
    print(f"    Concerns: {stats['meetings_with_concern']}")
    print(f"    Positive pivots: {stats['meetings_with_positive_pivot']}")
    
    return stats


if __name__ == "__main__":
    df = load_meetings()
    stats = quick_stats(df)
```

---

## ✅ ACCEPTANCE CRITERIA

After running `python -m src.loader`:

1. ✅ DataFrame has 100 rows (or close — if some fail, print which ones)
2. ✅ `meetings_flat.csv` exists in `outputs/`
3. ✅ `quick_stats()` prints reasonable numbers:
   - Date range spans multiple weeks
   - Avg duration is 20-50 min
   - Sentiment distribution has multiple values
   - Some meetings have key moment flags set
4. ✅ No exceptions thrown on any meeting
5. ✅ All columns from schema are present and correctly typed

---

## 🧪 QUICK VALIDATION TEST

After loading, run these checks in the notebook:

```python
df = load_meetings()
assert len(df) == 100, f"Expected 100 meetings, got {len(df)}"
assert df["meeting_id"].nunique() == 100, "Duplicate meeting IDs!"
assert df["duration_min"].between(0, 500).all(), "Suspicious durations"
assert df["sentiment_score"].between(0, 5).all(), "Sentiment out of range"
assert df["title"].notna().all(), "Missing titles"
print("✅ All loader checks passed")
```
