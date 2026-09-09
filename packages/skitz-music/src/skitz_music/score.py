"""Version-one symbolic score: one fixed meter, monophonic tracks, exact quarter units."""

import hashlib
import json
import re
from fractions import Fraction
from typing import Literal

from music21 import pitch
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Event(Record):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    offset: str
    duration: str
    pitch: str | None = None
    tie: Literal["start", "continue", "stop"] | None = None
    articulation: Literal["staccato", "tenuto", "accent"] | None = None

    @field_validator("offset", "duration")
    @classmethod
    def rational(cls, value: str) -> str:
        if not re.fullmatch(r"\d+(?:/\d+)?", value):
            raise ValueError("Use exact nonnegative quarter units, e.g. '3/2'")
        try:
            number = Fraction(value)
        except ZeroDivisionError as exc:
            raise ValueError("Zero denominator") from exc
        if number > 100000 or number.denominator > 4096:
            raise ValueError("Rhythm exceeds supported bounds")
        return str(number)

    @field_validator("pitch")
    @classmethod
    def spelled_pitch(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[A-G](?:#{1,2}|-{1,2})?[0-8]", value):
            raise ValueError("Use spelled music21 pitches, e.g. F#4 or B-3")
        if not 0 <= pitch.Pitch(value).midi <= 127:
            raise ValueError("Pitch outside MIDI range")
        return value

    @model_validator(mode="after")
    def positive_duration(self):
        if Fraction(self.duration) <= 0:
            raise ValueError("Duration must be positive")
        if self.pitch is None and self.tie:
            raise ValueError("Rests cannot be tied")
        return self


class Track(Record):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(max_length=120)
    program: int = Field(default=0, ge=0, le=127)
    events: tuple[Event, ...] = Field(max_length=10000)


class Score(Record):
    schema_version: Literal[1] = 1
    title: str = Field(default="Untitled", max_length=200)
    meter: str = "3/4"
    tempo: int = Field(default=90, ge=20, le=300)
    key: str = "g minor"
    tracks: tuple[Track, ...] = Field(min_length=1, max_length=32)

    @field_validator("meter")
    @classmethod
    def valid_meter(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[1-9]|1[0-6])/(?:1|2|4|8|16)", value):
            raise ValueError("Unsupported meter")
        return value

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Ga-g](?:#|-)? (?:major|minor)", value):
            raise ValueError("Use a tonic and mode, e.g. 'g minor'")
        return value

    @model_validator(mode="after")
    def unique_ids(self):
        track_ids = [track.id for track in self.tracks]
        event_ids = [event.id for track in self.tracks for event in track.events]
        if len(set(track_ids)) != len(track_ids) or len(set(event_ids)) != len(event_ids):
            raise ValueError("Track IDs and event IDs must be unique")
        return self

    @property
    def bar_length(self) -> Fraction:
        return Fraction(self.meter) * 4

    @property
    def revision(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()

    def events_by_id(self) -> dict[str, tuple[str, Event]]:
        return {event.id: (track.id, event) for track in self.tracks for event in track.events}
