"""Tests for the data loader, including the new per-turn transcript fields."""

from src.loader import (
    _speaker_role_resolver,
    _parse_transcript_turns,
    SENTIMENT_VALUE,
)


class TestSpeakerRoleResolver:
    INFO = {
        "organizerEmail": "megan.lawson@aegiscloud.com",
        "allEmails": ["megan.lawson@aegiscloud.com", "raj.kapoor@aegiscloud.com"],
    }

    def test_vendor_staff_is_rep(self):
        resolve = _speaker_role_resolver(self.INFO)
        assert resolve("Megan Lawson") == "rep"
        assert resolve("Raj Kapoor") == "rep"

    def test_single_domain_unknown_is_internal(self):
        resolve = _speaker_role_resolver(self.INFO)
        assert resolve("Outside Guest") == "internal"

    def test_customer_in_multi_domain_call(self):
        info = {
            "organizerEmail": "sarah.chen@aegiscloud.com",
            "allEmails": ["sarah.chen@aegiscloud.com", "greg@summittrust.com"],
        }
        resolve = _speaker_role_resolver(info)
        assert resolve("Sarah Chen") == "rep"
        # Unmatched name in a 2-domain call -> customer
        assert resolve("Gregory Fisk") == "customer"

    def test_empty_name(self):
        resolve = _speaker_role_resolver(self.INFO)
        assert resolve("") == "unknown"


class TestParseTurns:
    def test_maps_sentiment_and_role(self):
        info = {"organizerEmail": "a.b@aegiscloud.com", "allEmails": ["a.b@aegiscloud.com"]}
        resolve = _speaker_role_resolver(info)
        data = [
            {"speaker_name": "A B", "sentimentType": "negative", "speaker_id": 0, "time": 1.0,
             "sentence": "bad"},
            {"speaker_name": "A B", "sentimentType": "positive", "speaker_id": 0, "time": 2.0,
             "sentence": "good"},
        ]
        turns = _parse_transcript_turns(data, resolve)
        assert len(turns) == 2
        assert turns[0]["sentiment_value"] == SENTIMENT_VALUE["negative"]
        assert turns[1]["role"] == "rep"

    def test_skips_non_dicts(self):
        resolve = _speaker_role_resolver({"organizerEmail": "x@y.com", "allEmails": []})
        turns = _parse_transcript_turns(["junk", {"sentimentType": "neutral"}], resolve)
        assert len(turns) == 1


class TestRealData:
    def test_loads_100_meetings_with_turns(self, real_df):
        assert len(real_df) == 100
        assert "transcript_turns" in real_df.columns
        # Every meeting should have at least some turns
        assert (real_df["transcript_turns"].apply(len) > 0).all()

    def test_roles_assigned(self, real_df):
        all_roles = {t["role"] for turns in real_df["transcript_turns"] for t in turns}
        assert "rep" in all_roles
        assert "customer" in all_roles

    def test_quick_stats(self, real_df):
        from src.loader import quick_stats
        stats = quick_stats(real_df)
        assert stats["total_meetings"] == 100
        assert stats["total_unique_speakers"] > 0
        assert "sentiment_distribution" in stats

    def test_save_csv_excludes_heavy_columns(self):
        import pandas as pd
        from src.loader import load_meetings, OUTPUT_DIR, _HEAVY_COLS
        load_meetings(save_csv=True)
        saved = pd.read_csv(OUTPUT_DIR / "meetings_flat.csv")
        assert len(saved) == 100
        for col in _HEAVY_COLS:
            assert col not in saved.columns
