"""Tests for transcript-level (per-turn, speaker-attributed) sentiment."""

import pytest

from src.transcript_sentiment import (
    derived_meeting_sentiment,
    role_sentiment,
    meeting_sentiment_arc,
    late_call_sentiment,
    speaker_sentiment,
    add_transcript_features,
    generate_transcript_report,
)
from tests.conftest import make_turns


class TestDerived:
    def test_mean_of_values(self):
        turns = make_turns(["negative", "neutral", "positive"])  # 1,3,5
        assert derived_meeting_sentiment(turns) == 3.0

    def test_empty(self):
        assert derived_meeting_sentiment([]) is None


class TestRoleSentiment:
    def test_rep_vs_customer_split(self):
        turns = make_turns(["positive", "positive"], role="rep") + \
                make_turns(["negative", "negative"], role="customer")
        out = role_sentiment(turns)
        assert out["rep_sentiment"] == 5.0
        assert out["customer_sentiment"] == 1.0
        assert out["rep_minus_customer"] == 4.0
        assert out["customer_negative_share"] == 1.0

    def test_missing_role(self):
        out = role_sentiment(make_turns(["neutral"], role="rep"))
        assert out["customer_sentiment"] is None


class TestArc:
    def test_negative_pivot_detected(self):
        # starts positive, ends negative
        turns = make_turns(["positive"] * 3 + ["neutral"] * 3 + ["negative"] * 3)
        arc = meeting_sentiment_arc(turns)
        assert arc["has_negative_pivot"] is True
        assert arc["slope"] < 0
        assert arc["start"] > arc["end"]

    def test_flat_no_pivot(self):
        arc = meeting_sentiment_arc(make_turns(["neutral"] * 9))
        assert arc["has_negative_pivot"] is False

    def test_too_few_turns(self):
        arc = meeting_sentiment_arc(make_turns(["negative"]))
        assert arc["has_negative_pivot"] is False
        assert arc["slope"] is None


class TestLateCall:
    def test_uses_final_third(self):
        turns = make_turns(["positive"] * 6 + ["negative"] * 3)
        assert late_call_sentiment(turns) == 1.0

    def test_role_filter(self):
        turns = make_turns(["positive"] * 3, role="rep") + make_turns(["negative"] * 3, role="customer")
        assert late_call_sentiment(turns, role="customer") == 1.0


class TestSpeakerSentiment:
    def test_most_negative_speaker(self):
        turns = (
            [{"speaker": "Happy", "role": "rep", "sentiment_value": 5.0} for _ in range(3)]
            + [{"speaker": "Sad", "role": "customer", "sentiment_value": 1.0} for _ in range(3)]
        )
        out = speaker_sentiment(turns)
        assert out["most_negative_speaker"] == "Sad"

    def test_min_turns_filter(self):
        turns = [{"speaker": "Solo", "role": "rep", "sentiment_value": 1.0}]
        assert speaker_sentiment(turns, min_turns=3)["most_negative_speaker"] is None


class TestIntegration:
    def test_add_features_columns(self, real_df):
        for col in ["derived_sentiment", "customer_sentiment", "rep_sentiment",
                    "sentiment_arc_slope", "has_negative_pivot", "late_customer_sentiment"]:
            assert col in real_df.columns

    def test_add_features_requires_turns(self):
        import pandas as pd
        with pytest.raises(KeyError):
            add_transcript_features(pd.DataFrame({"meeting_id": ["x"]}))

    def test_report_runs(self, real_df):
        report = generate_transcript_report(real_df)
        assert report["meetings_analyzed"] == 100
        assert "insight" in report
