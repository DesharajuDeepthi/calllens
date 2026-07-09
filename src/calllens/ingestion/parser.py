"""Parse a single call folder into a validated ParsedCall."""

import hashlib
import json
from pathlib import Path

from calllens.ingestion.models import (
    CallSummary,
    MeetingInfo,
    ParsedCall,
    Transcript,
)


_REQUIRED_FILES = {
    "meeting-info.json",
    "transcript.json",
    "summary.json",
    "speaker-meta.json",
    "speakers.json",
    "events.json",
}


def _hash_folder(folder: Path) -> str:
    """SHA-256 of all JSON file contents combined — used as idempotency key."""
    h = hashlib.sha256()
    for fname in sorted(_REQUIRED_FILES):
        fpath = folder / fname
        if fpath.exists():
            h.update(fpath.read_bytes())
    return h.hexdigest()


def parse_call_folder(folder: Path) -> ParsedCall:
    """
    Parse all JSON files in a call folder and return a validated ParsedCall.
    Raises ValueError if required files are missing or validation fails.
    """
    missing = _REQUIRED_FILES - {f.name for f in folder.iterdir()}
    if missing:
        raise ValueError(f"Missing files in {folder.name}: {missing}")

    meeting_info = MeetingInfo.model_validate(
        json.loads((folder / "meeting-info.json").read_text())
    )
    transcript = Transcript.model_validate(
        json.loads((folder / "transcript.json").read_text())
    )
    summary = CallSummary.model_validate(
        json.loads((folder / "summary.json").read_text())
    )
    speaker_meta: dict[str, str] = json.loads(
        (folder / "speaker-meta.json").read_text()
    )

    return ParsedCall(
        folder_path=str(folder),
        content_hash=_hash_folder(folder),
        meeting_info=meeting_info,
        transcript=transcript,
        summary=summary,
        speaker_meta=speaker_meta,
    )
