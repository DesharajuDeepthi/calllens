"""
Eval metric helpers — no LLM required.

These functions operate on plain Python dicts sourced from the DB and
return numeric scores that can be asserted against thresholds in tests.
"""

from __future__ import annotations

import re
from typing import Sequence


# ── Classification accuracy ───────────────────────────────────────────────

# Title patterns that reliably determine call_type (applied in order)
_CALL_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"support case|ticket #|case #|support request", re.I), "support"),
    (re.compile(
        r"qbr|quarterly business review|business review|check.?in|"
        r"onboarding|renewal discussion|demo|discovery call|executive brief",
        re.I,
    ), "external"),
    (re.compile(
        r"team sync|team meeting|stand.?up|sprint|all.?hands|internal|"
        r"engineering|product review|retrospective",
        re.I,
    ), "internal"),
]


def oracle_call_type(title: str) -> str | None:
    """
    Return the expected call_type inferred from the call title.
    Returns None when the title is ambiguous and no oracle rule matches.
    """
    for pattern, expected in _CALL_TYPE_PATTERNS:
        if pattern.search(title):
            return expected
    return None


def classification_accuracy(
    rows: Sequence[dict],
) -> tuple[float, list[dict]]:
    """
    Compute accuracy of call_type classifications against oracle title rules.

    rows: list of dicts with at least {"title": str, "call_type": str}

    Returns (accuracy_score, mismatches) where accuracy is computed only on
    rows for which the oracle can infer an expected label (ambiguous rows are
    excluded from both numerator and denominator).
    """
    correct = 0
    total = 0
    mismatches: list[dict] = []

    for row in rows:
        expected = oracle_call_type(row["title"])
        if expected is None:
            continue  # oracle can't determine — skip
        total += 1
        if row["call_type"] == expected:
            correct += 1
        else:
            mismatches.append({
                "title": row["title"],
                "expected": expected,
                "actual": row["call_type"],
            })

    score = correct / total if total > 0 else 0.0
    return score, mismatches


# ── Insight coverage ──────────────────────────────────────────────────────

REQUIRED_INSIGHT_TYPES: dict[str, list[str]] = {
    "support_lead":    ["recurring_issue", "escalation_pattern"],
    "sales_manager":   ["churn_risk"],
    "product_manager": ["feature_gap"],
    "eng_lead":        ["infrastructure_risk"],
}


def insight_coverage(
    insights: Sequence[dict],
) -> tuple[float, dict[str, list[str]]]:
    """
    Check what fraction of required insight types are present per persona.

    insights: list of dicts with {"persona": str, "insight_type": str}

    Returns (coverage_score, missing) where missing is a dict mapping
    persona → list of missing insight_type strings.
    """
    by_persona: dict[str, set[str]] = {}
    for row in insights:
        by_persona.setdefault(row["persona"], set()).add(row["insight_type"])

    missing: dict[str, list[str]] = {}
    total_required = 0
    total_present = 0

    for persona, required in REQUIRED_INSIGHT_TYPES.items():
        present = by_persona.get(persona, set())
        missing_types = [t for t in required if t not in present]
        if missing_types:
            missing[persona] = missing_types
        total_required += len(required)
        total_present += len(required) - len(missing_types)

    score = total_present / total_required if total_required > 0 else 0.0
    return score, missing


# ── Sentiment direction check ─────────────────────────────────────────────

# Only use high-confidence signal words that reliably predict sentiment direction.
# Context-dependent words ("outage", "issue", "bug") are excluded because they
# appear in post-resolution retrospectives with positive sentiment too.
_NEGATIVE_KEYWORDS = re.compile(
    r"frustrated|cancell|churning?|angry|escalat|disappoint|"
    r"switching\s+(to|vendor|away)|unhappy|lost the account|"
    r"complete loss|termination|at risk of",
    re.I,
)
_POSITIVE_KEYWORDS = re.compile(
    r"love\s+the\s+product|excellent|fantastic|impressed|very satisfied|"
    r"exceeded\s+expectations|best\s+product|renewal confirmed",
    re.I,
)


def _sentiment_contains_negative(label: str) -> bool:
    """Match mixed-negative, very-negative, negative, etc."""
    return "negative" in label


def _sentiment_contains_positive(label: str) -> bool:
    """Match positive, mixed-positive, very-positive — but NOT any negative variant."""
    return "positive" in label and "negative" not in label


def sentiment_direction_accuracy(rows: Sequence[dict]) -> tuple[float, list[dict]]:
    """
    Check that calls whose summary contains strong negative/positive signals
    have the expected overall_sentiment.

    Sentiment labels in the DB use an extended taxonomy:
      negative, mixed-negative, very-negative,
      positive, mixed-positive, very-positive
    The oracle accepts any label that contains "negative" / "positive".

    rows: list of dicts with {"summary_text": str, "overall_sentiment": str, "title": str}
    """
    correct = total = 0
    mismatches: list[dict] = []

    for row in rows:
        sentiment = row.get("overall_sentiment", "")
        text = (row.get("summary_text") or "") + " " + (row.get("title") or "")

        if _NEGATIVE_KEYWORDS.search(text) and not _POSITIVE_KEYWORDS.search(text):
            total += 1
            if _sentiment_contains_negative(sentiment):
                correct += 1
            else:
                mismatches.append({
                    "title": row["title"],
                    "expected": "contains-negative",
                    "actual": sentiment,
                    "triggered_by": _NEGATIVE_KEYWORDS.search(text).group(),
                })
        elif _POSITIVE_KEYWORDS.search(text) and not _NEGATIVE_KEYWORDS.search(text):
            total += 1
            if _sentiment_contains_positive(sentiment):
                correct += 1
            else:
                mismatches.append({
                    "title": row["title"],
                    "expected": "contains-positive",
                    "actual": sentiment,
                    "triggered_by": _POSITIVE_KEYWORDS.search(text).group(),
                })

    score = correct / total if total > 0 else 1.0  # no oracle rows → vacuously pass
    return score, mismatches
