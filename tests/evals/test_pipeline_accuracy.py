"""
Pipeline accuracy gate — CI fails if any threshold is breached.

Thresholds (tunable via env):
  EVAL_CLASSIFICATION_THRESHOLD  default 0.75
  EVAL_SENTIMENT_THRESHOLD       default 0.70
  EVAL_MIN_CALLS                 default 100
  EVAL_MIN_INSIGHTS_PER_PERSONA  default 1

Run:
    pytest tests/evals/test_pipeline_accuracy.py -m eval -v
"""

from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from calllens.eval.metrics import (
    classification_accuracy,
    sentiment_direction_accuracy,
    insight_coverage,
    REQUIRED_INSIGHT_TYPES,
)

pytestmark = pytest.mark.eval

CLASSIFICATION_THRESHOLD = float(os.getenv("EVAL_CLASSIFICATION_THRESHOLD", "0.75"))
SENTIMENT_THRESHOLD = float(os.getenv("EVAL_SENTIMENT_THRESHOLD", "0.60"))
MIN_CALLS = int(os.getenv("EVAL_MIN_CALLS", "100"))
MIN_INSIGHTS_PER_PERSONA = int(os.getenv("EVAL_MIN_INSIGHTS_PER_PERSONA", "1"))


# ── Structural completeness ───────────────────────────────────────────────

async def test_all_calls_classified(call_count, all_classifications):
    """
    At least MIN_CALLS calls exist and ≥99% of them have a classification row.
    (Ingested-but-not-pipelined calls — e.g. test fixtures — account for the slack.)
    """
    assert call_count >= MIN_CALLS, (
        f"Expected ≥{MIN_CALLS} calls in DB, found {call_count}. "
        "Did you run the ingestion pipeline?"
    )
    coverage = len(all_classifications) / call_count
    assert coverage >= 0.99, (
        f"{call_count - len(all_classifications)} call(s) have no classification row "
        f"(coverage={coverage:.1%}). Run the pipeline again to classify them."
    )


async def test_all_calls_have_summaries(call_count, all_summaries):
    """Every call must have a summary row."""
    assert len(all_summaries) == call_count, (
        f"call_count={call_count} but summaries={len(all_summaries)}."
    )


async def test_all_personas_have_insights(all_insights):
    """Every persona must have at least MIN_INSIGHTS_PER_PERSONA insights."""
    by_persona: dict[str, int] = {}
    for row in all_insights:
        by_persona[row["persona"]] = by_persona.get(row["persona"], 0) + 1

    for persona in REQUIRED_INSIGHT_TYPES:
        count = by_persona.get(persona, 0)
        assert count >= MIN_INSIGHTS_PER_PERSONA, (
            f"Persona '{persona}' has {count} insights, expected ≥{MIN_INSIGHTS_PER_PERSONA}."
        )


async def test_insights_have_evidence(all_insights):
    """Insights must cite at least one evidence call, except low-severity ones."""
    missing_evidence = [
        ins for ins in all_insights
        if ins["severity"] in ("high", "critical")
        and not ins.get("evidence_call_ids")
    ]
    assert not missing_evidence, (
        f"{len(missing_evidence)} high/critical insights have no evidence_call_ids:\n"
        + "\n".join(f"  [{i['persona']}] {i['title']}" for i in missing_evidence[:5])
    )


# ── Accuracy gates ────────────────────────────────────────────────────────

async def test_classification_accuracy(all_classifications):
    """
    Call-type classifications must match title-oracle rules at ≥ threshold.
    Only rows where the oracle can infer an expected type are scored.
    """
    accuracy, mismatches = classification_accuracy(all_classifications)

    # Print a summary for debugging (visible with -v)
    if mismatches:
        print(f"\nClassification mismatches ({len(mismatches)}):")
        for m in mismatches[:10]:
            print(f"  expected={m['expected']:10s} actual={m['actual']:10s}  {m['title'][:60]}")

    assert accuracy >= CLASSIFICATION_THRESHOLD, (
        f"Classification accuracy {accuracy:.1%} < threshold {CLASSIFICATION_THRESHOLD:.1%}. "
        f"Mismatches: {len(mismatches)}"
    )


async def test_sentiment_direction_accuracy(all_summaries):
    """
    Calls with strong negative/positive keywords must have the expected sentiment.
    """
    accuracy, mismatches = sentiment_direction_accuracy(all_summaries)

    if mismatches:
        print(f"\nSentiment mismatches ({len(mismatches)}):")
        for m in mismatches[:10]:
            print(
                f"  expected={m['expected']:20s} actual={m['actual']:10s} "
                f"keyword={m['triggered_by']:20s}  {m['title'][:50]}"
            )

    assert accuracy >= SENTIMENT_THRESHOLD, (
        f"Sentiment accuracy {accuracy:.1%} < threshold {SENTIMENT_THRESHOLD:.1%}. "
        f"Mismatches: {len(mismatches)}"
    )


async def test_insight_type_coverage(all_insights):
    """
    Each persona must have at least the minimum required insight types.
    Coverage threshold: 100% (all explicitly required types must be present).
    Update REQUIRED_INSIGHT_TYPES in metrics.py if the pipeline generates
    different type names.
    """
    coverage, missing = insight_coverage(all_insights)

    if missing:
        print("\nMissing insight types per persona:")
        for persona, types in missing.items():
            print(f"  {persona}: {types}")
        print("\nActual insight types in DB:")
        from collections import defaultdict
        by_persona: dict = defaultdict(set)
        for r in all_insights:
            by_persona[r["persona"]].add(r["insight_type"])
        for p, types in sorted(by_persona.items()):
            print(f"  {p}: {sorted(types)}")

    assert coverage == 1.0, (
        f"Insight type coverage {coverage:.1%}. Missing required types: {missing}. "
        "Update REQUIRED_INSIGHT_TYPES in src/calllens/eval/metrics.py to match "
        "what the pipeline actually generates."
    )


# ── Regression guard ──────────────────────────────────────────────────────

BASELINE_FILE = Path(__file__).parent / "baseline_metrics.json"


async def test_save_metrics_baseline(
    all_classifications, all_summaries, all_insights, call_count, insight_count
):
    """
    Save current metric snapshot. On subsequent runs, compare against it.
    This test always passes — it writes the baseline if it doesn't exist,
    or compares and warns if metrics regress.
    """
    cls_accuracy, _ = classification_accuracy(all_classifications)
    sent_accuracy, _ = sentiment_direction_accuracy(all_summaries)
    cov, _ = insight_coverage(all_insights)

    current = {
        "calls": int(call_count),
        "insights": int(insight_count),
        "classification_accuracy": round(cls_accuracy, 4),
        "sentiment_accuracy": round(sent_accuracy, 4),
        "insight_coverage": round(cov, 4),
    }

    if not BASELINE_FILE.exists():
        BASELINE_FILE.write_text(json.dumps(current, indent=2))
        print(f"\nBaseline saved: {current}")
    else:
        baseline = json.loads(BASELINE_FILE.read_text())
        regressions = []
        for key in ("classification_accuracy", "sentiment_accuracy", "insight_coverage"):
            delta = current[key] - baseline[key]
            if delta < -0.05:  # allow ±5% drift
                regressions.append(
                    f"  {key}: {baseline[key]:.3f} → {current[key]:.3f} (Δ{delta:+.3f})"
                )
        if regressions:
            print("\nMETRIC REGRESSIONS DETECTED (>5% drop):\n" + "\n".join(regressions))
            print("Update baseline with: rm tests/evals/baseline_metrics.json && make eval")
            pytest.fail("Metrics regressed vs baseline. See above.")
        else:
            print(f"\nMetrics stable vs baseline: {current}")
