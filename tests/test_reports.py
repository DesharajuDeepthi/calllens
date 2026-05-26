"""Integration tests: run the sentiment and action-item reports end-to-end on real data."""

from src.sentiment import (
    sentiment_by_call_type,
    sentiment_by_sub_theme,
    sentiment_over_time,
    sentiment_vs_characteristics,
    find_negative_outliers,
    find_positive_outliers,
    generate_sentiment_report,
)
from src.action_tracker import (
    parse_action_item,
    extract_all_action_items,
    owner_workload,
    action_verb_distribution,
    recurring_action_themes,
    action_density_per_meeting,
    generate_action_items_report,
)


class TestSentimentAggregations:
    def test_by_call_type(self, real_df):
        out = sentiment_by_call_type(real_df)
        assert "insight" in out
        assert len(out["by_call_type"]) >= 1

    def test_by_sub_theme(self, real_df):
        assert "top_negative_themes" in sentiment_by_sub_theme(real_df)

    def test_over_time(self, real_df):
        out = sentiment_over_time(real_df)
        assert out["trend_direction"] in ("improving", "declining", "flat")

    def test_vs_characteristics(self, real_df):
        out = sentiment_vs_characteristics(real_df)
        assert "strongest_correlation" in out

    def test_outliers(self, real_df):
        assert len(find_negative_outliers(real_df, top_n=5)) == 5
        assert len(find_positive_outliers(real_df, top_n=5)) == 5

    def test_full_report(self, real_df):
        report = generate_sentiment_report(real_df)
        assert set(report.keys()) >= {"by_call_type", "over_time", "negative_outliers"}


class TestActionItems:
    def test_parse_owner_and_verb(self):
        parsed = parse_action_item("Megan Lawson: Draft the customer update by end of week")
        assert parsed["owner"] == "Megan Lawson"
        assert parsed["verb"] == "draft"
        assert parsed["has_deadline"] is True

    def test_parse_no_owner(self):
        parsed = parse_action_item("Follow up on the ticket")
        assert parsed["owner"] is None

    def test_parse_rejects_long_owner(self):
        # A long prefix before the colon is not a real owner
        parsed = parse_action_item("This is a very long sentence prefix: do the thing")
        assert parsed["owner"] is None

    def test_extract_and_analyses(self, real_df):
        items = extract_all_action_items(real_df)
        assert len(items) > 0
        assert owner_workload(items)["total_owners"] > 0
        assert action_verb_distribution(items)["top_verb"]
        assert "recurring_keywords" in recurring_action_themes(items)
        assert "by_call_type" in action_density_per_meeting(real_df)

    def test_full_report(self, real_df):
        report = generate_action_items_report(real_df)
        assert report["total_action_items"] > 0
