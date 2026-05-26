"""Tests for cross-meeting account journeys."""

from src.account_journey import (
    _trajectory,
    build_account_journey,
    build_all_journeys,
    trajectory_lookup,
    generate_journey_report,
)


class TestTrajectory:
    def test_declining(self):
        out = _trajectory([5.0, 4.0, 2.0, 1.0])
        assert out["label"] == "declining"
        assert out["slope"] < 0

    def test_improving(self):
        out = _trajectory([1.0, 2.5, 4.0, 5.0])
        assert out["label"] == "improving"

    def test_stable(self):
        assert _trajectory([3.0, 3.1, 2.9, 3.0])["label"] == "stable"

    def test_volatile(self):
        # oscillating with ~zero net slope -> volatile, not trending
        assert _trajectory([1.0, 5.0, 1.0, 5.0, 1.0])["label"] == "volatile"

    def test_single_point(self):
        assert _trajectory([3.0])["label"] == "single_point"


class TestJourneys:
    def test_acme_is_declining(self, synthetic_df):
        j = build_account_journey(synthetic_df, "Acme Corp")
        assert j["meeting_count"] == 3
        assert j["trajectory"]["label"] == "declining"
        assert j["first_sentiment"] > j["last_sentiment"]
        assert j["avg_cadence_days"] is not None

    def test_build_all_filters_min_meetings(self, synthetic_df):
        journeys = build_all_journeys(synthetic_df, min_meetings=2)
        accounts = {j["account"] for j in journeys}
        assert "Acme Corp" in accounts      # 3 meetings
        assert "Globex" not in accounts     # only 1 meeting

    def test_trajectory_lookup(self, synthetic_df):
        journeys = build_all_journeys(synthetic_df, min_meetings=2)
        lookup = trajectory_lookup(journeys)
        assert lookup["Acme Corp"]["label"] == "declining"

    def test_report_real_data(self, real_df):
        report = generate_journey_report(real_df)
        assert "trajectory_distribution" in report
        assert report["accounts_with_history"] >= 0
