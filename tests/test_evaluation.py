"""Tests for the evaluation harness."""

from src.evaluation import (
    confusion_matrix,
    classification_report,
    evaluate_categorization,
    sentiment_validation,
    churn_weight_sensitivity,
    _spearman,
)


class TestConfusionMatrix:
    def test_diagonal_perfect(self):
        cm = confusion_matrix(["a", "b", "a"], ["a", "b", "a"], labels=["a", "b"])
        assert cm.loc["a", "a"] == 2
        assert cm.loc["b", "b"] == 1
        assert cm.loc["a", "b"] == 0

    def test_off_diagonal(self):
        cm = confusion_matrix(["a", "a"], ["a", "b"], labels=["a", "b"])
        assert cm.loc["a", "b"] == 1


class TestClassificationReport:
    def test_perfect(self):
        r = classification_report(["a", "b"], ["a", "b"])
        assert r["accuracy"] == 1.0
        assert r["macro_f1"] == 1.0

    def test_half_wrong(self):
        r = classification_report(["a", "a", "b", "b"], ["a", "b", "b", "a"])
        assert r["accuracy"] == 0.5

    def test_per_class_precision_recall(self):
        r = classification_report(["a", "a", "b"], ["a", "b", "b"])
        assert r["per_class"]["a"]["recall"] == 0.5
        assert r["per_class"]["b"]["precision"] == 0.5


class TestSpearman:
    def test_monotonic(self):
        assert _spearman([1, 2, 3], [10, 20, 30]) == 1.0

    def test_inverse(self):
        assert _spearman([1, 2, 3], [30, 20, 10]) == -1.0

    def test_constant(self):
        assert _spearman([1, 1, 1], [1, 2, 3]) == 0.0


class TestChurnSensitivity:
    RANKINGS = [
        {"account": "A", "components": {"churn_signals": 50, "sentiment": 10}},
        {"account": "B", "components": {"churn_signals": 10, "sentiment": 30}},
        {"account": "C", "components": {"churn_signals": 0, "sentiment": 5}},
    ]

    def test_returns_scenarios(self):
        out = churn_weight_sensitivity(self.RANKINGS, top_k=2)
        assert "scenarios" in out
        assert 0.0 <= out["avg_top_k_overlap"] <= 1.0

    def test_empty(self):
        assert "insight" in churn_weight_sensitivity([])


class TestEvaluateCategorization:
    def test_real_data_accuracy(self, real_df):
        out = evaluate_categorization(real_df)
        assert out["n_labelled"] >= 30
        # The classifier should comfortably beat random (3 classes) on the labelled sample
        assert out["accuracy"] > 0.6
        assert set(out["per_class"].keys()) == {"support", "external", "internal"}


class TestSentimentValidation:
    def test_real_data(self, real_df):
        out = sentiment_validation(real_df)
        assert out["n"] > 0
        assert -1.0 <= out["pearson_corr"] <= 1.0
        assert "direction_agreement" in out
