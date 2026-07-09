"""Pydantic models for the raw JSON files in each call folder."""

from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator


# ── meeting-info.json ──────────────────────────────────────────────────────

class MeetingInfo(BaseModel):
    meeting_id: str = Field(alias="meetingId")
    title: str
    organizer_email: str = Field(alias="organizerEmail")
    host: str
    start_time: datetime = Field(alias="startTime")
    end_time: datetime = Field(alias="endTime")
    duration: float  # minutes
    all_emails: list[str] = Field(alias="allEmails", default_factory=list)
    invitees: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ── transcript.json ────────────────────────────────────────────────────────

class TranscriptTurn(BaseModel):
    sentence: str
    speaker_name: str
    sentiment_type: str | None = Field(alias="sentimentType", default=None)
    speaker_id: int | None = None
    time: float | None = None          # start time in seconds
    end_time: float | None = Field(alias="endTime", default=None)
    average_confidence: float | None = Field(alias="averageConfidence", default=None)
    index: int

    model_config = {"populate_by_name": True}


class Transcript(BaseModel):
    data: list[TranscriptTurn]


# ── summary.json ───────────────────────────────────────────────────────────

class KeyMoment(BaseModel):
    time: float
    text: str


class CallSummary(BaseModel):
    summary: str
    action_items: list[str] = Field(alias="actionItems", default_factory=list)
    topics: list[str] = Field(default_factory=list)
    overall_sentiment: str | None = Field(alias="overallSentiment", default=None)
    sentiment_score: float | None = Field(alias="sentimentScore", default=None)
    key_moments: list[KeyMoment] = Field(alias="keyMoments", default_factory=list)

    model_config = {"populate_by_name": True}


# ── Parsed call (all files combined) ──────────────────────────────────────

class ParsedCall(BaseModel):
    folder_path: str
    content_hash: str
    meeting_info: MeetingInfo
    transcript: Transcript
    summary: CallSummary
    speaker_meta: dict[str, str]  # speaker_id (str) → name
