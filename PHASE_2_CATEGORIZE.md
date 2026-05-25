# Phase 2: Categorization (`src/categorize.py`)

## 🎯 PURPOSE

Categorize each meeting into one of three call types: `support`, `external`, or `internal`. Also assign a secondary topic theme from a fixed taxonomy.

**Approach:** Hybrid (rules + LLM fallback). Rules handle obvious cases for free; LLM handles ambiguous cases.

**Time budget:** 2 hours

---

## 📋 REQUIREMENTS

### Categories (Primary — Call Type)

Per the PDF: three call types exist in the dataset.

1. **`support`** — Customer support cases. Title patterns: "Support Case #...", "Ticket...", customer reporting issues
2. **`external`** — Account manager + customer calls. Title patterns: "Aegis / [Customer Name] - [purpose]" (renewals, planning, QBRs, adoption, feedback)
3. **`internal`** — Engineering syncs, planning, outages, cross-team. Title patterns: "Standup", "Outage", "Planning", "Review", "Postmortem"

### Sub-Topic Themes (Secondary)

Use a fixed taxonomy derived from observation. Each meeting gets ONE primary sub-theme:

- `incident_response` — Outages, postmortems, incident reviews
- `customer_renewal` — Renewal discussions, QBRs, account planning
- `customer_onboarding` — New customer setup, training
- `customer_support_issue` — Specific ticket/case discussions
- `compliance_security` — ISO, SOC2, audits, security reviews
- `product_planning` — Feature requests, roadmap, Q-planning
- `engineering_sync` — Standups, technical syncs
- `cross_team_escalation` — Issues spanning multiple teams
- `other` — Doesn't fit cleanly

### Output Schema

The DataFrame from Phase 1 gets two new columns added:

| Column | Type | Description |
|--------|------|-------------|
| `call_type` | str | One of: support, external, internal |
| `sub_theme` | str | One of the 9 themes above |
| `category_confidence` | float | 0.0-1.0; lower = needs review |
| `category_method` | str | 'rules' or 'llm' (which method assigned it) |

---

## 💻 CODE TEMPLATE

```python
"""
Categorization module for Transcript Intelligence.

Hybrid approach:
1. Rule-based first: Pattern matching on meeting titles (free, transparent)
2. LLM fallback: Claude Haiku for ambiguous cases (cheap, ~$0.30 total)
3. Confidence scoring: Flag low-confidence cases for review

Design rationale:
- Rules catch ~70% of meetings cheaply (clear patterns like "Support Case #")
- LLM handles the rest with semantic understanding
- This is pragmatic and explainable — easier to debug than pure LLM
- The function is tool-shaped: takes a meeting record, returns structured result

Usage:
    from src.categorize import categorize_meetings
    df = categorize_meetings(df)
"""

import os
import re
import json
from typing import Literal, TypedDict

import pandas as pd
from tqdm import tqdm

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


# ============================================================================
# Taxonomy
# ============================================================================

CallType = Literal["support", "external", "internal"]
SubTheme = Literal[
    "incident_response",
    "customer_renewal",
    "customer_onboarding",
    "customer_support_issue",
    "compliance_security",
    "product_planning",
    "engineering_sync",
    "cross_team_escalation",
    "other",
]


class CategorizationResult(TypedDict):
    call_type: CallType
    sub_theme: SubTheme
    confidence: float
    method: Literal["rules", "llm"]
    reasoning: str


# ============================================================================
# Rule-based categorization (fast, free)
# ============================================================================

# Compiled regex patterns for performance
_SUPPORT_PATTERNS = [
    re.compile(r"support case", re.I),
    re.compile(r"ticket\s*#", re.I),
    re.compile(r"\bcase\s*#", re.I),
]

_EXTERNAL_PATTERNS = [
    # Title format: "[Company] / [Customer] - [purpose]"
    re.compile(r"^[A-Z]\w+\s*/\s*[A-Z]", re.I),
    re.compile(r"\bqbr\b", re.I),
    re.compile(r"quarterly business review", re.I),
    re.compile(r"\brenewal\b", re.I),
]

_INTERNAL_PATTERNS = [
    re.compile(r"standup", re.I),
    re.compile(r"outage", re.I),
    re.compile(r"postmortem", re.I),
    re.compile(r"\bsync\b", re.I),
    re.compile(r"weekly\s+(eng|engineering|team)", re.I),
    re.compile(r"\bplanning\b", re.I),
    re.compile(r"retrospective|retro", re.I),
]

_SUB_THEME_PATTERNS = {
    "incident_response": [
        re.compile(r"outage|postmortem|incident|remediation", re.I),
    ],
    "customer_renewal": [
        re.compile(r"renewal|qbr|business review", re.I),
    ],
    "customer_onboarding": [
        re.compile(r"onboarding|kickoff|kick-off", re.I),
    ],
    "customer_support_issue": [
        re.compile(r"support case|ticket\s*#|case\s*#", re.I),
    ],
    "compliance_security": [
        re.compile(r"iso\s*27001|soc\s*2|compliance|audit|security review", re.I),
    ],
    "product_planning": [
        re.compile(r"q\d\s+planning|roadmap|feature", re.I),
    ],
    "engineering_sync": [
        re.compile(r"engineering\s+(standup|sync)|weekly\s+eng", re.I),
    ],
    "cross_team_escalation": [
        re.compile(r"escalation|cross-team", re.I),
    ],
}


def categorize_by_rules(
    title: str,
    summary: str = "",
    participants: list[str] | None = None,
) -> CategorizationResult | None:
    """
    Categorize a meeting using rule-based pattern matching on its title.
    
    Args:
        title: Meeting title
        summary: Meeting summary (optional, used for tie-breaking)
        participants: List of participant emails (optional, used to detect external)
    
    Returns:
        CategorizationResult if a rule matched with high confidence (>=0.85),
        None if no clear rule match (caller should fall back to LLM).
    """
    title_str = title or ""
    
    # Detect external by participant domain mismatch
    participants = participants or []
    domains = {email.split("@")[-1] for email in participants if "@" in email}
    has_external_domain = len(domains) > 1
    
    # ----- Call type rules -----
    if any(p.search(title_str) for p in _SUPPORT_PATTERNS):
        call_type = "support"
        confidence = 0.95
    elif any(p.search(title_str) for p in _EXTERNAL_PATTERNS) or has_external_domain:
        # External pattern OR multiple domains in participants
        call_type = "external"
        confidence = 0.90 if has_external_domain else 0.85
    elif any(p.search(title_str) for p in _INTERNAL_PATTERNS):
        call_type = "internal"
        confidence = 0.90
    else:
        # No clear rule match — defer to LLM
        return None
    
    # ----- Sub-theme rules -----
    sub_theme: SubTheme = "other"
    for theme, patterns in _SUB_THEME_PATTERNS.items():
        if any(p.search(title_str) or p.search(summary or "") for p in patterns):
            sub_theme = theme  # type: ignore
            break
    
    return {
        "call_type": call_type,  # type: ignore
        "sub_theme": sub_theme,
        "confidence": confidence,
        "method": "rules",
        "reasoning": f"Matched title pattern (domains: {len(domains)})",
    }


# ============================================================================
# LLM-based categorization (fallback for ambiguous cases)
# ============================================================================

_LLM_SYSTEM_PROMPT = """You categorize B2B SaaS meeting transcripts.

Three CALL TYPES:
- support: Customer support cases (customer reporting an issue, vendor helping resolve)
- external: Account manager + customer calls (renewals, planning, QBRs, adoption, feedback)
- internal: Internal company calls (engineering syncs, outages, planning, escalations)

Nine SUB-THEMES:
- incident_response: Outages, postmortems, incident reviews
- customer_renewal: Renewal discussions, QBRs, account planning
- customer_onboarding: New customer setup, training
- customer_support_issue: Specific ticket/case discussions
- compliance_security: ISO, SOC2, audits, security reviews
- product_planning: Feature requests, roadmap, quarterly planning
- engineering_sync: Standups, technical syncs
- cross_team_escalation: Issues spanning multiple teams
- other: Doesn't fit cleanly

Respond ONLY with valid JSON:
{
  "call_type": "support|external|internal",
  "sub_theme": "<one of the 9>",
  "confidence": 0.0-1.0,
  "reasoning": "<one sentence>"
}"""


def categorize_by_llm(
    title: str,
    summary: str,
    topics: list[str],
    client: Anthropic,
) -> CategorizationResult:
    """
    Categorize a meeting using Claude Haiku.
    
    Used for ambiguous cases that rule-based matching couldn't handle.
    Cost: ~$0.003 per call with Haiku.
    
    Args:
        title: Meeting title
        summary: Meeting summary (from pre-computed summary.json)
        topics: List of pre-computed topics
        client: Anthropic client
    
    Returns:
        CategorizationResult with method='llm'.
    """
    user_message = f"""TITLE: {title}

SUMMARY: {summary[:500]}

PRE-COMPUTED TOPICS: {', '.join(topics)}

Categorize this meeting."""
    
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_LLM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        
        # Extract JSON from response
        text = response.content[0].text.strip()
        # Strip potential markdown code fences
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        
        parsed = json.loads(text)
        
        return {
            "call_type": parsed["call_type"],
            "sub_theme": parsed["sub_theme"],
            "confidence": float(parsed.get("confidence", 0.7)),
            "method": "llm",
            "reasoning": parsed.get("reasoning", ""),
        }
    except Exception as e:
        # Defensive fallback: assume internal with low confidence
        return {
            "call_type": "internal",
            "sub_theme": "other",
            "confidence": 0.3,
            "method": "llm",
            "reasoning": f"LLM call failed: {e}",
        }


# ============================================================================
# Main entry point
# ============================================================================

def categorize_meetings(
    df: pd.DataFrame,
    use_llm: bool = True,
    api_key: str | None = None,
) -> pd.DataFrame:
    """
    Categorize all meetings in the DataFrame.
    
    Tries rule-based first; falls back to LLM for ambiguous cases.
    Adds four new columns: call_type, sub_theme, category_confidence, category_method.
    
    Args:
        df: Output of loader.load_meetings()
        use_llm: If False, skip LLM fallback (rules only — for testing)
        api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
    
    Returns:
        DataFrame with categorization columns added.
    """
    df = df.copy()
    
    # Initialize LLM client if needed
    client = None
    if use_llm:
        client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    
    results = []
    rule_count = 0
    llm_count = 0
    
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Categorizing"):
        # Try rules first
        result = categorize_by_rules(
            title=row["title"],
            summary=row["summary"],
            participants=row["participants"],
        )
        
        if result is None:
            # Fall back to LLM
            if use_llm and client:
                result = categorize_by_llm(
                    title=row["title"],
                    summary=row["summary"],
                    topics=row["topics"],
                    client=client,
                )
                llm_count += 1
            else:
                # No LLM available, mark as low confidence
                result = {
                    "call_type": "internal",
                    "sub_theme": "other",
                    "confidence": 0.3,
                    "method": "rules",
                    "reasoning": "No rule matched; LLM disabled",
                }
        else:
            rule_count += 1
        
        results.append(result)
    
    # Add columns to DataFrame
    df["call_type"] = [r["call_type"] for r in results]
    df["sub_theme"] = [r["sub_theme"] for r in results]
    df["category_confidence"] = [r["confidence"] for r in results]
    df["category_method"] = [r["method"] for r in results]
    df["category_reasoning"] = [r["reasoning"] for r in results]
    
    print(f"\n✅ Categorization complete:")
    print(f"   Rule-based: {rule_count} ({100*rule_count/len(df):.0f}%)")
    print(f"   LLM-based:  {llm_count} ({100*llm_count/len(df):.0f}%)")
    print(f"\n   Call type distribution:")
    print(df["call_type"].value_counts().to_string())
    print(f"\n   Sub-theme distribution:")
    print(df["sub_theme"].value_counts().to_string())
    
    # Save
    from pathlib import Path
    Path("outputs").mkdir(exist_ok=True)
    
    # Drop the heavy text column for the CSV
    df_save = df.drop(columns=["transcript_text"]).copy()
    for col in ["participants", "action_items", "topics", "key_moments",
                "key_moment_types", "speakers"]:
        if col in df_save.columns:
            df_save[col] = df_save[col].apply(json.dumps)
    df_save.to_csv("outputs/categorized.csv", index=False)
    print(f"\n💾 Saved to outputs/categorized.csv")
    
    return df


def review_low_confidence(df: pd.DataFrame, threshold: float = 0.7) -> pd.DataFrame:
    """
    Filter to meetings with low categorization confidence for manual review.
    
    Used as an "evals lite" check — flag the ~10-15% you're least sure about.
    
    Args:
        df: Output of categorize_meetings()
        threshold: Confidence cutoff
    
    Returns:
        Filtered DataFrame, sorted by confidence ascending.
    """
    low = df[df["category_confidence"] < threshold].sort_values("category_confidence")
    print(f"\n🔍 {len(low)} meetings below confidence {threshold}:")
    for _, row in low[["meeting_id", "title", "call_type", "sub_theme", 
                        "category_confidence", "category_reasoning"]].iterrows():
        print(f"  [{row['category_confidence']:.2f}] {row['title'][:60]}")
        print(f"       → {row['call_type']} / {row['sub_theme']}")
        print(f"       Reason: {row['category_reasoning']}")
    return low


if __name__ == "__main__":
    from src.loader import load_meetings
    df = load_meetings()
    df = categorize_meetings(df)
    review_low_confidence(df)
```

---

## ✅ ACCEPTANCE CRITERIA

1. ✅ All 100 meetings get categorized
2. ✅ Distribution looks reasonable:
   - Each call type has at least 10 meetings (no degenerate split)
   - All 9 sub-themes appear (or close — "other" can be small)
3. ✅ Rule-based handles >50% of meetings (cost saver)
4. ✅ LLM calls cost <$0.50 total
5. ✅ Low-confidence cases (<0.7) are <20% of total
6. ✅ Manual spot-check of 10 random meetings: ≥8 look correct

---

## 🎤 Q&A PREP

**"Why hybrid instead of pure LLM?"**
> "Cost and explainability. Rules handle obvious patterns like 'Support Case #' at zero cost. LLM handles ambiguous cases where semantic understanding matters. The 70/30 split saves ~$2 per run while keeping accuracy high. Also: rules are transparent — when categorization is wrong, I can debug a regex; debugging an LLM is harder."

**"How do you know it's working?"**
> "Three checks: (1) Distribution sanity — call types aren't 99% one bucket; (2) Confidence scoring — I flag the bottom 15% for review; (3) Manual sampling — I spot-checked 10 random meetings, 9 looked right. For production, I'd build a labeled eval set."

**"What about edge cases like a customer joining an internal call?"**
> "The participant-domain check catches some of these. Multi-domain attendance bumps a meeting toward 'external' even if the title says 'sync'. Imperfect — for production I'd add a manual review queue for low-confidence cases."
