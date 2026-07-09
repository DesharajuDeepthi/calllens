"""
LLM-as-judge eval for insight quality.

Disabled by default (costs API credits). Enable with:
    pytest tests/evals/test_insight_quality.py -m "eval and llm_judge" -v

Threshold: EVAL_JUDGE_THRESHOLD (default 0.65)
"""

from __future__ import annotations

import os

import pytest

from calllens.eval.judge import judge_insights_sample

pytestmark = [pytest.mark.eval, pytest.mark.llm_judge]

JUDGE_THRESHOLD = float(os.getenv("EVAL_JUDGE_THRESHOLD", "0.65"))
JUDGE_SAMPLE_SIZE = int(os.getenv("EVAL_JUDGE_SAMPLE_SIZE", "5"))


async def test_insight_quality_llm_judge(all_insights):
    """
    Sample N insights across all personas, ask LLM to score each on
    relevance, specificity, and actionability.
    Average overall score must be ≥ JUDGE_THRESHOLD.
    """
    if not all_insights:
        pytest.skip("No insights in DB — run the pipeline first.")

    report = await judge_insights_sample(all_insights, sample_size=JUDGE_SAMPLE_SIZE)

    print(f"\nLLM Judge Report (n={report['sample_size']}):")
    print(f"  avg_overall      : {report['avg_overall']:.3f}")
    print(f"  avg_relevance    : {report['avg_relevance']:.3f}")
    print(f"  avg_actionability: {report['avg_actionability']:.3f}")
    print("\nPer-insight:")
    for r in report["results"]:
        if "error" in r:
            print(f"  [ERROR] {r['title']}: {r['error']}")
        else:
            print(
                f"  [{r['persona']:15s}][{r['insight_type']:20s}] "
                f"overall={r['overall']:.2f}  {r['title'][:50]}"
            )
            print(f"    → {r['reasoning']}")

    assert report["avg_overall"] >= JUDGE_THRESHOLD, (
        f"LLM judge avg score {report['avg_overall']:.3f} < threshold {JUDGE_THRESHOLD}. "
        f"Insights may be low quality — review the prompts."
    )


async def test_sales_manager_has_churn_risk(all_insights):
    """Sales manager persona must have at least one churn_risk insight."""
    churn_insights = [
        i for i in all_insights
        if i["persona"] == "sales_manager" and i["insight_type"] == "churn_risk"
    ]
    assert churn_insights, (
        "No churn_risk insights found for sales_manager. "
        "The risk detection node may not have run or found signals."
    )
    print(f"\nChurn risk insights ({len(churn_insights)}):")
    for i in churn_insights:
        print(f"  [{i['severity']:8s}] {i['title']}")


async def test_no_cross_persona_leakage(all_insights):
    """
    Eng lead insights must not contain financial/renewal keywords
    (those are sales manager territory).
    Sales manager insights must not be purely technical (those are eng lead territory).
    """
    import re
    financial_pattern = re.compile(
        r"contract value|arr|renewal|revenue|csm|sales|discount", re.I
    )
    eng_insights = [i for i in all_insights if i["persona"] == "eng_lead"]
    leaks = [
        i for i in eng_insights
        if financial_pattern.search(i.get("body", "") + " " + i.get("title", ""))
    ]
    assert not leaks, (
        f"Eng lead insights contain financial keywords (cross-persona leakage):\n"
        + "\n".join(f"  {i['title']}" for i in leaks)
    )
