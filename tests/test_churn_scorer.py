"""Tests for churn scoring, including the new transcript + trajectory signals."""

from src.churn_scorer import (
    _transcript_score,
    _trajectory_score,
    score_account,
    score_all_accounts,
    add_account_column,
    chart_top_risk_accounts,
    chart_risk_components,
)


class TestNewComponents:
    def test_trajectory_score(self):
        assert _trajectory_score({"label": "declining"}) == 10.0
        assert _trajectory_score({"label": "volatile"}) == 5.0
        assert _trajectory_score({"label": "improving"}) == 0.0
        assert _trajectory_score(None) == 0.0

    def test_transcript_score_absent_columns(self, synthetic_df):
        df = synthetic_df.drop(columns=["late_customer_sentiment", "has_negative_pivot"])
        assert _transcript_score(df) == 0.0

    def test_transcript_score_rewards_negativity(self, synthetic_df):
        acme = synthetic_df[synthetic_df["account"] == "Acme Corp"]
        assert _transcript_score(acme) > 0


class TestScoreAccount:
    def test_acme_is_high_risk(self, synthetic_df):
        result = score_account(synthetic_df, "Acme Corp", trajectory={"label": "declining"})
        assert result["risk_score"] > 50
        assert result["risk_level"] in ("Alert", "Critical")
        assert result["components"]["trajectory"] == 10.0
        assert len(result["evidence"]) > 0

    def test_score_capped_at_100(self, synthetic_df):
        result = score_account(synthetic_df, "Acme Corp", trajectory={"label": "declining"})
        assert result["risk_score"] <= 100

    def test_healthy_account(self, synthetic_df):
        result = score_account(synthetic_df, "Globex")
        assert result["risk_level"] == "Healthy"

    def test_unknown_account(self, synthetic_df):
        result = score_account(synthetic_df, "Does Not Exist")
        assert result["risk_level"] == "Unknown"
        assert result["meeting_count"] == 0


class TestScoreAll:
    def test_ranking_descending(self, synthetic_df):
        rankings = score_all_accounts(synthetic_df)
        scores = [r["risk_score"] for r in rankings]
        assert scores == sorted(scores, reverse=True)

    def test_with_journeys(self, synthetic_df):
        from src.account_journey import build_all_journeys
        journeys = build_all_journeys(synthetic_df, min_meetings=2)
        rankings = score_all_accounts(synthetic_df, journeys=journeys)
        acme = next(r for r in rankings if r["account"] == "Acme Corp")
        assert acme["components"]["trajectory"] == 10.0

    def test_real_data_and_charts(self, real_df):
        rankings = score_all_accounts(real_df)
        assert len(rankings) > 0
        assert all(r["risk_score"] <= 100 for r in rankings)
        # charts should render without raising
        chart_top_risk_accounts(rankings)
        chart_risk_components(rankings)
