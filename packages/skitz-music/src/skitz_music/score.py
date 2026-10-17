"""Version-two symbolic score: exact quarter units, chord-capable tracks and measure maps.

Each track is one rhythmic line: its events never overlap, and an event is a rest, a
note or a chord. Meter and tempo may change, but only at the start of a measure.
Schema-one documents (one `pitch` per event, one fixed `meter` and `tempo`) are
migrated losslessly when they are validated.
"""

import hashlib
import json
import re
from bisect import bisect_right
from fractions import Fraction
from typing import Literal

from music21 import pitch
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 2
ID_PATTERN = r"^[a-zA-Z0-9_-]{1,80}$"
METER_PATTERN = r"^(?:[1-9]|1[0-6])/(?:1|2|4|8|16)$"
MAX_CHORD_SIZE = 12
MAX_MEASURE = 100000


def canonical_json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def rational(value: str) -> str:
    if not re.fullmatch(r"\d+(?:/\d+)?", value):
        raise ValueError("Use exact nonnegative quarter units, e.g. '3/2'")
    try:
        number = Fraction(value)
    except ZeroDivisionError as exc:
        raise ValueError("Zero denominator") from exc
    if number > 100000 or number.denominator > 4096:
        raise ValueError("Rhythm exceeds supported bounds")
    return str(number)


def spelled_pitch(value: str) -> str:
    if not re.fullmatch(r"[A-G](?:#{1,2}|-{1,2})?[0-8]", value):
        raise ValueError(f"Use spelled music21 pitches, e.g. F#4 or B-3 (got {value!r})")
    if not 0 <= pitch.Pitch(value).midi <= 127:
        raise ValueError(f"Pitch outside MIDI range: {value}")
    return value


def chord_pitches(values: tuple[str, ...]) -> tuple[str, ...]:
    """Check spelling and return the pitches low to high; a chord cannot double a key."""
    checked = [spelled_pitch(value) for value in values]
    keys = [pitch.Pitch(value).midi for value in checked]
    if len(set(keys)) != len(keys):
        raise ValueError("A chord cannot repeat a pitch, including enharmonic unisons")
    return tuple(value for _, value in sorted(zip(keys, checked, strict=True)))


def pitch_shorthand(data):
    """Accept `pitch` (one pitch or null) as input shorthand for `pitches`."""
    if isinstance(data, dict) and "pitch" in data:
        if "pitches" in data:
            raise ValueError("Give pitch or pitches, not both")
        data = dict(data)
        value = data.pop("pitch")
        data["pitches"] = [] if value is None else [value]
    return data


def bar_length(meter: str) -> Fraction:
    return Fraction(meter) * 4


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Pitches = tuple[str, ...]
Tie = Literal["start", "continue", "stop"]
Articulation = Literal["staccato", "tenuto", "accent"]


class Event(Record):
    id: str = Field(pattern=ID_PATTERN)
    offset: str = Field(description="Start, in quarter notes from the beginning, e.g. '9/2'")
    duration: str = Field(description="Length in quarter notes, e.g. '1/2' for an eighth note")
    pitches: Pitches = Field(
        default=(),
        max_length=MAX_CHORD_SIZE,
        description=(
            "Spelled pitches such as F#4 or B-3: none for a rest, one for a note, several "
            "for a chord (stored low to high)"
        ),
    )
    tie: Tie | None = Field(
        default=None, description="Ties the whole event to the next/previous one with equal pitches"
    )
    articulation: Articulation | None = None

    @model_validator(mode="before")
    @classmethod
    def shorthand(cls, data):
        return pitch_shorthand(data)

    @field_validator("offset", "duration")
    @classmethod
    def exact(cls, value: str) -> str:
        return rational(value)

    @field_validator("pitches")
    @classmethod
    def spelled(cls, value: Pitches) -> Pitches:
        return chord_pitches(value)

    @model_validator(mode="after")
    def positive_duration(self):
        if Fraction(self.duration) <= 0:
            raise ValueError("Duration must be positive")
        if not self.pitches and self.tie:
            raise ValueError("Rests cannot be tied")
        return self

    @property
    def start(self) -> Fraction:
        return Fraction(self.offset)

    @property
    def end(self) -> Fraction:
        return Fraction(self.offset) + Fraction(self.duration)


class Track(Record):
    """One rhythmic line. Events never overlap; simultaneous rhythms need separate tracks."""

    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(max_length=120)
    program: int = Field(default=0, ge=0, le=127)
    events: tuple[Event, ...] = Field(max_length=10000)


class MeterChange(Record):
    measure: int = Field(ge=1, le=MAX_MEASURE, description="One-based measure the meter starts at")
    meter: str = Field(pattern=METER_PATTERN, description="Time signature, e.g. '6/8'")


class TempoChange(Record):
    measure: int = Field(ge=1, le=MAX_MEASURE, description="One-based measure the tempo starts at")
    bpm: int = Field(ge=20, le=300, description="Quarter notes per minute")


class MeasureGrid:
    """Measure boundaries implied by a meter map. The last meter continues indefinitely."""

    def __init__(self, meter_map: tuple[MeterChange, ...]):
        self.numbers: list[int] = []
        self.starts: list[Fraction] = []
        self.lengths: list[Fraction] = []
        self.meters: list[str] = []
        time = Fraction(0)
        for index, change in enumerate(meter_map):
            if index:
                time += (change.measure - self.numbers[-1]) * self.lengths[-1]
            self.numbers.append(change.measure)
            self.starts.append(time)
            self.lengths.append(bar_length(change.meter))
            self.meters.append(change.meter)

    def _by_measure(self, number: int) -> int:
        if number < 1:
            raise ValueError("Measures are one-based")
        return bisect_right(self.numbers, number) - 1

    def measure_at(self, time: Fraction) -> int:
        """The one-based measure that contains `time`."""
        index = bisect_right(self.starts, time) - 1
        return self.numbers[index] + int((time - self.starts[index]) // self.lengths[index])

    def bounds(self, number: int) -> tuple[Fraction, Fraction]:
        index = self._by_measure(number)
        start = self.starts[index] + (number - self.numbers[index]) * self.lengths[index]
        return start, start + self.lengths[index]

    def meter(self, number: int) -> str:
        return self.meters[self._by_measure(number)]

    def is_boundary(self, time: Fraction) -> bool:
        return self.bounds(self.measure_at(time))[0] == time

    def span(self, start: Fraction, end: Fraction) -> range:
        """Measures touched by the half-open interval [start, end)."""
        last = self.measure_at(end) - (1 if self.is_boundary(end) else 0)
        return range(self.measure_at(start), max(last, self.measure_at(start)) + 1)

    def count(self, end: Fraction) -> int:
        """Number of measures needed to hold [0, end)."""
        return self.span(Fraction(0), end)[-1] if end > 0 else 0


class Score(Record):
    schema_version: Literal[2] = SCHEMA_VERSION
    title: str = Field(default="Untitled", max_length=200)
    key: str = "g minor"
    meter_map: tuple[MeterChange, ...] = Field(
        default=(MeterChange(measure=1, meter="3/4"),),
        min_length=1,
        max_length=1000,
        description="Meter changes, starting at measure 1, at increasing measures",
    )
    tempo_map: tuple[TempoChange, ...] = Field(
        default=(TempoChange(measure=1, bpm=90),),
        min_length=1,
        max_length=1000,
        description="Tempo changes, starting at measure 1, at increasing measures",
    )
    tracks: tuple[Track, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="before")
    @classmethod
    def migrate(cls, data):
        """Upgrade schema 1 and accept `meter`/`tempo` shorthand for single-entry maps."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("schema_version") == 1:
            data["schema_version"] = SCHEMA_VERSION
            data.setdefault("meter", "3/4")
            data.setdefault("tempo", 90)
        for short, field, value in (("meter", "meter_map", "meter"), ("tempo", "tempo_map", "bpm")):
            if short in data:
                if field in data:
                    raise ValueError(f"Give {short} or {field}, not both")
                data[field] = [{"measure": 1, value: data.pop(short)}]
        return data

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Ga-g](?:#|-)? (?:major|minor)", value):
            raise ValueError("Use a tonic and mode, e.g. 'g minor'")
        return value

    @field_validator("meter_map", "tempo_map")
    @classmethod
    def ordered_map(cls, value: tuple, info):
        if value[0].measure != 1:
            raise ValueError(f"{info.field_name} must start at measure 1")
        for previous, change in zip(value, value[1:], strict=False):
            if change.measure <= previous.measure:
                raise ValueError(f"{info.field_name} measures must increase")
            if change.model_dump(exclude={"measure"}) == previous.model_dump(exclude={"measure"}):
                raise ValueError(
                    f"{info.field_name} entry at measure {change.measure} repeats the current "
                    "value; remove it"
                )
        return value

    @model_validator(mode="after")
    def unique_ids(self):
        track_ids = [track.id for track in self.tracks]
        event_ids = [event.id for track in self.tracks for event in track.events]
        if len(set(track_ids)) != len(track_ids) or len(set(event_ids)) != len(event_ids):
            raise ValueError("Track IDs and event IDs must be unique")
        return self

    @property
    def grid(self) -> MeasureGrid:
        return MeasureGrid(self.meter_map)

    @property
    def end(self) -> Fraction:
        return max((e.end for t in self.tracks for e in t.events), default=Fraction(0))

    def tempo_at(self, measure: int) -> int:
        numbers = [change.measure for change in self.tempo_map]
        return self.tempo_map[bisect_right(numbers, measure) - 1].bpm

    @property
    def revision(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.model_dump(mode="json"))

    def events_by_id(self) -> dict[str, tuple[str, Event]]:
        return {event.id: (track.id, event) for track in self.tracks for event in track.events}
