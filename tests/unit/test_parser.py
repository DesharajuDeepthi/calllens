"""Unit tests for the call folder parser — no database needed."""

from pathlib import Path
import pytest
from calllens.ingestion.parser import parse_call_folder

# Path to real data — skip if not present (CI won't have it)
DATA_ROOT = Path("/Users/deepthidesharaju/Documents/Transcript Intelligence/data/raaw")
pytestmark = pytest.mark.skipif(
    not DATA_ROOT.exists(), reason="Transcript data not available"
)


def test_parse_single_folder():
    folder = next(DATA_ROOT.iterdir())
    parsed = parse_call_folder(folder)

    assert parsed.meeting_info.meeting_id
    assert parsed.meeting_info.title
    assert len(parsed.transcript.data) > 0
    assert parsed.summary.summary
    assert parsed.content_hash and len(parsed.content_hash) == 64


def test_parse_is_deterministic():
    """Same folder parsed twice must produce the same content_hash."""
    folder = next(DATA_ROOT.iterdir())
    a = parse_call_folder(folder)
    b = parse_call_folder(folder)
    assert a.content_hash == b.content_hash


def test_all_100_folders_parse():
    """Every folder in the dataset must parse without errors."""
    folders = [d for d in DATA_ROOT.iterdir() if d.is_dir()]
    assert len(folders) == 100, f"Expected 100 folders, got {len(folders)}"

    errors = []
    for folder in folders:
        try:
            parse_call_folder(folder)
        except Exception as exc:
            errors.append((folder.name, str(exc)))

    assert not errors, f"Parse failures:\n" + "\n".join(f"  {n}: {e}" for n, e in errors)
