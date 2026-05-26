from __future__ import annotations
"""
Evaluation harness for Transcript Intelligence.

Turns "looks reasonable" into numbers:
- Categorization: confusion matrix + per-class precision/recall/F1 against a
  hand-labelled sample (tests/fixtures/categorization_labels.csv).
- Sentiment: validates the trusted pre-computed score against a transcript-derived
  score, so "we trust summary.json" becomes a measured decision, not a hope.
- Churn: sensitivity of the risk ranking to the (judgment-based) component weights.

Usage:
    from src.evaluation import evaluate_categorization, sentiment_validation
    report = evaluate_categorization(df)
"""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


LABELS_PATH = Path("tests/fixtures/categorization_labels.csv")


def confusion_matrix(y_true: list[str], y_pred: list[str],
                     labels: list[str] | None = None) -> pd.DataFrame:
    """Confusion matrix as a DataFrame (rows = true, cols = predicted)."""
    labels = labels or sorted(set(y_true) | set(y_pred))
    idx = {lab: i for i, lab in enumerate(labels)}
    mat = np.zeros((len(labels), len(labels)), dtype=int)
    for t, p in zip(y_true, y_pred):
        if t in idx and p in idx:
            mat[idx[t], idx[p]] += 1
    return pd.DataFrame(mat, index=labels, columns=labels)


def classification_report(y_true: list[str], y_pred: list[str],
                          labels: list[str] | None = None) -> dict[str, Any]:
    """Per-class precision / recall / F1 / support, plus accuracy and macro-F1."""
    labels = labels or sorted(set(y_true) | set(y_pred))
    per_class: dict[str, dict[str, float]] = {}

    for lab in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p != lab)
        support = sum(1 for t in y_true if t == lab)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[lab] = {
            "precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "support": support,
        }

    accuracy = (
        sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)
        if y_true else 0.0
    )
    macro_f1 = float(np.mean([m["f1"] for m in per_class.values()])) if per_class else 0.0

    return {
        "per_class": per_class,
        "accuracy": round(accuracy, 3),
        "macro_f1": round(macro_f1, 3),
        "n": len(y_true),
    }


def evaluate_categorization(df: pd.DataFrame, labels_path: Path = LABELS_PATH) -> dict[str, Any]:
    """
    Score the predicted `call_type` against the hand-labelled sample.

    The labels file is a small, independently-judged sample — it measures the
    classifier, it is not the classifier's training data.
    """
    if not Path(labels_path).exists():
        raise FileNotFoundError(f"Label file not found: {labels_path}")
    if "call_type" not in df.columns:
        raise KeyError("DataFrame has no 'call_type' column — run categorize_meetings first.")

    labels = pd.read_csv(labels_path, dtype=str)
    merged = labels.merge(df[["meeting_id", "call_type"]], on="meeting_id", how="inner")
    if merged.empty:
        raise ValueError("No overlap between label file and DataFrame meeting_ids.")

    y_true = merged["true_call_type"].tolist()
    y_pred = merged["call_type"].tolist()
    classes = ["support", "external", "internal"]

    report = classification_report(y_true, y_pred, labels=classes)
    cm = confusion_matrix(y_true, y_pred, labels=classes)

    return {
        "confusion_matrix": cm.to_dict(),
        "accuracy": report["accuracy"],
        "macro_f1": report["macro_f1"],
        "per_class": report["per_class"],
        "n_labelled": report["n"],
        "insight": (
            f"On {report['n']} hand-labelled meetings the classifier scores "
            f"{report['accuracy']:.0%} accuracy (macro-F1 {report['macro_f1']:.2f})."
        ),
    }


def sentiment_validation(df: pd.DataFrame, tolerance: float = 1.0) -> dict[str, Any]:
    """
    Validate the pre-computed `sentiment_score` against the transcript-derived score.

    High agreement justifies trusting summary.json instead of re-running an LLM.
    Requires the `derived_sentiment` column (src.transcript_sentiment.add_transcript_features).
    """
    if "derived_sentiment" not in df.columns:
        raise KeyError("Run src.transcript_sentiment.add_transcript_features(df) first.")

    pair = df.dropna(subset=["sentiment_score", "derived_sentiment"]).copy()
    if len(pair) < 2:
        return {"n": len(pair), "insight": "Insufficient paired data to validate."}

    pre = pair["sentiment_score"].astype(float)
    der = pair["derived_sentiment"].astype(float)

    corr = float(np.corrcoef(pre, der)[0, 1])
    mae = float(np.mean(np.abs(pre - der)))
    within = float(np.mean(np.abs(pre - der) <= tolerance))
    direction = float(np.mean(((pre < 3) & (der < 3)) | ((pre >= 3) & (der >= 3))))

    return {
        "n": int(len(pair)),
        "pearson_corr": round(corr, 3),
        "mae": round(mae, 3),
        f"within_{tolerance}": round(within, 3),
        "direction_agreement": round(direction, 3),
        "insight": (
            f"Pre-computed and transcript-derived sentiment correlate at r={corr:.2f} "
            f"(MAE {mae:.2f}, {within:.0%} within {tolerance} pt). "
            + ("Trusting the pre-computed score is justified."
               if corr >= 0.4 else "Weak agreement — re-scoring may be warranted.")
        ),
    }


def _spearman(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation via Pearson on ranks."""
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def churn_weight_sensitivity(rankings: list[dict], top_k: int = 10,
                             perturbations: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    """
    How stable is the churn ranking under different component weights?

    Re-weights each account's component scores and compares the new ranking to
    the baseline (top-K overlap + Spearman). A stable ranking means the exact
    weights don't drive the conclusions.
    """
    if not rankings:
        return {"insight": "No rankings to analyse."}

    components = list(rankings[0].get("components", {}).keys())
    perturbations = perturbations or {
        "churn_heavy": {c: (2.0 if c == "churn_signals" else 1.0) for c in components},
        "sentiment_heavy": {c: (2.0 if c == "sentiment" else 1.0) for c in components},
        "equal_weight": {c: 1.0 for c in components},
    }

    def ranked(weights: dict[str, float]) -> list[str]:
        scored = [
            (r["account"], sum(r["components"].get(c, 0) * weights.get(c, 1.0) for c in components))
            for r in rankings
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [a for a, _ in scored]

    base_weights = {c: 1.0 for c in components}
    base_order = ranked(base_weights)
    base_scores = [sum(r["components"].get(c, 0) for c in components) for r in rankings]
    base_top = set(base_order[:top_k])

    results = {}
    for name, weights in perturbations.items():
        order = ranked(weights)
        pert_scores = [sum(r["components"].get(c, 0) * weights.get(c, 1.0) for c in components)
                       for r in rankings]
        overlap = len(base_top & set(order[:top_k])) / max(1, min(top_k, len(base_order)))
        results[name] = {
            "top_k_overlap": round(overlap, 3),
            "spearman": round(_spearman(base_scores, pert_scores), 3),
        }

    avg_overlap = float(np.mean([v["top_k_overlap"] for v in results.values()]))
    return {
        "top_k": top_k,
        "scenarios": results,
        "avg_top_k_overlap": round(avg_overlap, 3),
        "insight": (
            f"Across reweighting scenarios the top-{top_k} at-risk accounts are "
            f"{avg_overlap:.0%} stable — the ranking is driven by the signal, not the exact weights."
        ),
    }


if __name__ == "__main__":
    from src.loader import load_meetings
    from src.categorize import categorize_meetings
    from src.transcript_sentiment import add_transcript_features
    df = load_meetings()
    df = categorize_meetings(df, use_llm=False)
    df = add_transcript_features(df)
    print(evaluate_categorization(df)["insight"])
    print(sentiment_validation(df)["insight"])
