"""Tests for topic analysis, including the new canonicalization."""

from src.topic_analyzer import (
    _normalize_topic,
    build_topic_canonical_map,
    topic_frequency,
    topic_sentiment_correlation,
    topic_co_occurrence,
    topic_timeline,
    generate_topic_report,
)


class TestCanonicalization:
    def test_normalize_singularises(self):
        assert _normalize_topic("Compliance Reports") == frozenset({"compliance", "report"})

    def test_subset_merges(self):
        counts = {"compliance": 23, "compliance reporting": 19}
        cmap = build_topic_canonical_map(counts)
        # more frequent topic wins as canonical
        assert cmap["compliance reporting"] == "compliance"
        assert cmap["compliance"] == "compliance"

    def test_distinct_topics_not_merged(self):
        counts = {"renewal": 10, "outage": 8}
        cmap = build_topic_canonical_map(counts)
        assert cmap["renewal"] == "renewal"
        assert cmap["outage"] == "outage"


class TestFrequency:
    def test_canonicalize_reduces_topic_count(self, real_df):
        plain = topic_frequency(real_df, min_count=3, canonicalize=False)
        canon = topic_frequency(real_df, min_count=3, canonicalize=True)
        assert canon["unique_topics_count"] <= plain["unique_topics_count"]

    def test_min_count_threshold(self, synthetic_df):
        out = topic_frequency(synthetic_df, min_count=2)
        recurring_topics = {r["topic"] for r in out["recurring"]}
        # "renewal" and "outage" each appear in 2 meetings
        assert "renewal" in recurring_topics
        assert "outage" in recurring_topics


class TestOtherAnalyses:
    def test_sentiment_correlation(self, synthetic_df):
        out = topic_sentiment_correlation(synthetic_df, min_count=2)
        assert "most_negative_topics" in out
        # outage appears in low-sentiment meetings
        neg = {t["topic"] for t in out["most_negative_topics"]}
        assert "outage" in neg

    def test_co_occurrence(self, synthetic_df):
        out = topic_co_occurrence(synthetic_df, min_pairs=1)
        assert isinstance(out["pairs"], list)

    def test_timeline(self, synthetic_df):
        out = topic_timeline(synthetic_df, top_n=5)
        assert "tracked_topics" in out


class TestReport:
    def test_real_data_report(self, real_df):
        report = generate_topic_report(real_df)
        assert report["frequency"]["recurring_count"] > 0
        assert "insight" in report["sentiment_correlation"]
