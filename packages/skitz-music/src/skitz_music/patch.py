"""Typed score patches. Edits apply in order to a working copy; the store then checks the
whole result (schema, structure, authorized measures, protected tracks) before saving.

Nothing moves implicitly: an edit that frees or overlaps time must be balanced by other
edits in the same patch, or the structural check rejects the whole patch.
"""

from fractions import Fraction
from typing import Annotated, Literal

from music21 import interval, pitch
from pydantic import Discriminator, Field, Tag, TypeAdapter, field_validator, model_validator

from .score import (
    ID_PATTERN,
    MAX_CHORD_SIZE,
    MAX_MEASURE,
    METER_PATTERN,
    Articulation,
    Event,
    MeasureGrid,
    MeterChange,
    Pitches,
    Record,
    Score,
    TempoChange,
    Tie,
    Track,
    chord_pitches,
    pitch_shorthand,
    rational,
    spelled_pitch,
)

EventId = Annotated[str, Field(pattern=ID_PATTERN)]
Measure = Annotated[int, Field(ge=1, le=MAX_MEASURE)]


def contiguous(measures: tuple[int, ...]) -> tuple[int, ...]:
    if list(measures) != list(range(measures[0], measures[0] + len(measures))):
        raise ValueError("List measures in order without gaps, e.g. [3, 4, 5]")
    return measures


class EventChanges(Record):
    pitches: Pitches | None = Field(default=None, max_length=MAX_CHORD_SIZE)
    tie: Tie | None = None
    articulation: Articulation | None = None
    duration: str | None = Field(
        default=None, description="New length; balance it with other edits so nothing overlaps"
    )

    @model_validator(mode="before")
    @classmethod
    def shorthand(cls, data):
        return pitch_shorthand(data)

    @field_validator("pitches")
    @classmethod
    def spelled(cls, value: Pitches | None) -> Pitches:
        if value is None:
            raise ValueError("Use [] for a rest")
        return chord_pitches(value)

    @field_validator("duration")
    @classmethod
    def exact(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Give a duration such as '1/2'")
        return rational(value)

    @model_validator(mode="after")
    def not_empty(self):
        if not self.model_fields_set:
            raise ValueError("set needs pitches (or pitch), tie, articulation or duration")
        return self


class PassageEvent(Record):
    """An event of a `replace` passage; its offset follows from the events before it."""

    id: EventId
    duration: str
    pitches: Pitches = Field(default=(), max_length=MAX_CHORD_SIZE)
    tie: Tie | None = None
    articulation: Articulation | None = None

    @model_validator(mode="before")
    @classmethod
    def shorthand(cls, data):
        return pitch_shorthand(data)

    @field_validator("duration")
    @classmethod
    def exact(cls, value: str) -> str:
        return rational(value)

    @field_validator("pitches")
    @classmethod
    def spelled(cls, value: Pitches) -> Pitches:
        return chord_pitches(value)


class SetEdit(Record):
    """Change an event's pitches, tie, articulation or duration. Its offset stays put."""

    op: Literal["set"] = "set"
    event_id: EventId
    set: EventChanges


class InsertEdit(Record):
    """Add an event with a new ID at an exact offset in time freed by other edits."""

    op: Literal["insert"]
    track_id: str
    event: Event


class DeleteEdit(Record):
    """Remove an event. Other edits in the patch must fill its time."""

    op: Literal["delete"]
    event_id: EventId


class SplitEdit(Record):
    """Cut an event into consecutive parts with the same pitches. The first part keeps the
    ID and articulation; incoming and outgoing ties stay on the outer parts."""

    op: Literal["split"]
    event_id: EventId
    durations: tuple[str, ...] = Field(
        min_length=2, max_length=64, description="Part lengths in order; they add up to the event"
    )
    new_ids: tuple[EventId, ...] = Field(description="IDs for every part after the first")
    tie: bool = Field(default=False, description="Tie the parts instead of restriking them")

    @field_validator("durations")
    @classmethod
    def exact(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(rational(item) for item in value)

    @model_validator(mode="after")
    def one_id_per_part(self):
        if len(self.new_ids) != len(self.durations) - 1:
            raise ValueError("Give one new ID for each part after the first")
        return self


class MergeEdit(Record):
    """Join back-to-back events of one track into the earliest, which keeps its ID, pitches
    and articulation and lasts their combined time."""

    op: Literal["merge"]
    event_ids: tuple[EventId, ...] = Field(min_length=2, max_length=64)


class ReplaceEdit(Record):
    """Rewrite one track's content in whole measures. The track's events that start in the
    measures are removed, and the new events are laid end to end from the first measure's
    start; they must fill the measures exactly. Reusing a removed event's ID keeps its
    identity; any other ID must be new. An event that starts earlier and runs into the
    measures must be split at the barline first."""

    op: Literal["replace"]
    track_id: str
    measures: tuple[Measure, ...] = Field(min_length=1)
    events: tuple[PassageEvent, ...] = Field(min_length=1, max_length=2000)

    @field_validator("measures")
    @classmethod
    def in_order(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        return contiguous(value)


class TransposeEdit(Record):
    """Transpose a track's pitches by a spelled interval, in whole measures or throughout."""

    op: Literal["transpose"]
    track_id: str
    interval: str = Field(
        pattern=r"^-?(?:P|M|m|A|d)[1-9][0-9]?$",
        description="Spelled interval, e.g. 'M2', '-P5', 'm3', 'P8'; negative is down",
    )
    measures: tuple[Measure, ...] | None = Field(
        default=None, description="Measures to transpose; omit for the whole track"
    )

    @field_validator("interval")
    @classmethod
    def real_interval(cls, value: str) -> str:
        try:
            interval.Interval(value)
        except Exception as exc:  # music21 raises its own exception types
            raise ValueError(f"Not a spelled interval: {value}") from exc
        return value


class TempoEdit(Record):
    """Set the tempo from a measure on, or remove that change with bpm null."""

    op: Literal["set_tempo"]
    measure: Measure
    bpm: Annotated[int, Field(ge=20, le=300)] | None


class MeterEdit(Record):
    """Set the meter from a measure on, or remove that change with meter null."""

    op: Literal["set_meter"]
    measure: Measure
    meter: Annotated[str, Field(pattern=METER_PATTERN)] | None


def _kind(value) -> str | None:
    if isinstance(value, dict):
        return value.get("op", "set")
    return getattr(value, "op", None)


PatchEdit = Annotated[
    Annotated[SetEdit, Tag("set")]
    | Annotated[InsertEdit, Tag("insert")]
    | Annotated[DeleteEdit, Tag("delete")]
    | Annotated[SplitEdit, Tag("split")]
    | Annotated[MergeEdit, Tag("merge")]
    | Annotated[ReplaceEdit, Tag("replace")]
    | Annotated[TransposeEdit, Tag("transpose")]
    | Annotated[TempoEdit, Tag("set_tempo")]
    | Annotated[MeterEdit, Tag("set_meter")],
    Discriminator(_kind),
]
EDITS = TypeAdapter(list[PatchEdit])


class ScorePatch(Record):
    """The patch file read by `skitz patch` and the arguments of apply_score_patch."""

    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    edits: list[PatchEdit] = Field(max_length=1000)
    allowed_measures: list[Measure] = Field(min_length=1)
    reason: str = "edit"


def _tie_sides(value: str | None) -> tuple[bool, bool]:
    return {None: (False, False), "start": (False, True), "continue": (True, True)}.get(
        value, (True, False)
    )


def _tie(incoming: bool, outgoing: bool) -> str | None:
    return {(False, True): "start", (True, True): "continue", (True, False): "stop"}.get(
        (incoming, outgoing)
    )


def _set_change(changes: list, model, measure: int, field: str, value) -> list:
    values = {change.measure: getattr(change, field) for change in changes}
    if value is None:
        if measure == 1:
            raise ValueError("Measure 1 needs a value; set a new one instead of removing it")
        if measure not in values:
            raise ValueError(f"There is no change at measure {measure} to remove")
        del values[measure]
    else:
        values[measure] = value
    result, current = [], None
    for number in sorted(values):
        if values[number] != current:
            result.append(model(measure=number, **{field: values[number]}))
            current = values[number]
    return result


class _Working:
    def __init__(self, score: Score, protected: set[str]):
        self.score = score
        self.protected = protected
        self.meter_map = list(score.meter_map)
        self.tempo_map = list(score.tempo_map)
        self.tracks = {t.id: [e.model_dump() for e in t.events] for t in score.tracks}
        self.known_ids = set(score.events_by_id())

    @property
    def grid(self) -> MeasureGrid:
        return MeasureGrid(tuple(self.meter_map))

    def _track(self, track_id: str) -> list[dict]:
        if track_id not in self.tracks:
            raise ValueError(f"Unknown track ID: {track_id}")
        if track_id in self.protected:
            raise ValueError(f"Protected track: {track_id}")
        return self.tracks[track_id]

    def _find(self, event_id: str) -> tuple[str, dict]:
        for track_id, events in self.tracks.items():
            for event in events:
                if event["id"] == event_id:
                    self._track(track_id)
                    return track_id, event
        raise ValueError(f"Unknown event ID: {event_id}")

    def _fresh(self, ids: list[str], reusable: set[str] = frozenset()):
        if len(set(ids)) != len(ids):
            raise ValueError("Event IDs in one edit must be distinct")
        current = {e["id"] for events in self.tracks.values() for e in events}
        for event_id in ids:
            if event_id not in reusable and (event_id in self.known_ids or event_id in current):
                raise ValueError(f"Event ID already used: {event_id}")

    def _replace_event(self, track_id: str, event: dict, parts: list[dict]):
        events = self.tracks[track_id]
        index = next(i for i, item in enumerate(events) if item is event)
        events[index : index + 1] = parts

    def set(self, edit: SetEdit):
        _, event = self._find(edit.event_id)
        event.update({name: getattr(edit.set, name) for name in edit.set.model_fields_set})

    def insert(self, edit: InsertEdit):
        events = self._track(edit.track_id)
        self._fresh([edit.event.id])
        events.append(edit.event.model_dump())
        events.sort(key=lambda e: Fraction(e["offset"]))

    def delete(self, edit: DeleteEdit):
        track_id, event = self._find(edit.event_id)
        self._replace_event(track_id, event, [])

    def split(self, edit: SplitEdit):
        track_id, event = self._find(edit.event_id)
        lengths = [Fraction(item) for item in edit.durations]
        if min(lengths) <= 0:
            raise ValueError("Every part needs a positive duration")
        if sum(lengths) != Fraction(event["duration"]):
            raise ValueError(
                f"Parts add up to {sum(lengths)} quarters but {edit.event_id} lasts "
                f"{event['duration']}"
            )
        if edit.tie and not event["pitches"]:
            raise ValueError("Rests cannot be tied")
        self._fresh(list(edit.new_ids))
        incoming, outgoing = _tie_sides(event["tie"])
        start = Fraction(event["offset"])
        parts = []
        for index, (length, event_id) in enumerate(
            zip(lengths, (edit.event_id, *edit.new_ids), strict=True)
        ):
            first, last = index == 0, index == len(lengths) - 1
            parts.append(
                {
                    **event,
                    "id": event_id,
                    "offset": str(start),
                    "duration": str(length),
                    "tie": _tie(incoming if first else edit.tie, outgoing if last else edit.tie),
                    "articulation": event["articulation"] if first else None,
                }
            )
            start += length
        self._replace_event(track_id, event, parts)

    def merge(self, edit: MergeEdit):
        if len(set(edit.event_ids)) != len(edit.event_ids):
            raise ValueError("Event IDs in one edit must be distinct")
        found = [self._find(event_id) for event_id in edit.event_ids]
        if len({track_id for track_id, _ in found}) != 1:
            raise ValueError("Merged events must be in one track")
        events = sorted((event for _, event in found), key=lambda e: Fraction(e["offset"]))
        for previous, event in zip(events, events[1:], strict=False):
            if Fraction(previous["offset"]) + Fraction(previous["duration"]) != Fraction(
                event["offset"]
            ):
                raise ValueError(f"{previous['id']} and {event['id']} are not back to back")
        first = events[0]
        first["duration"] = str(sum(Fraction(e["duration"]) for e in events))
        first["tie"] = _tie(_tie_sides(first["tie"])[0], _tie_sides(events[-1]["tie"])[1])
        for event in events[1:]:
            self._replace_event(found[0][0], event, [])

    def replace(self, edit: ReplaceEdit):
        events = self._track(edit.track_id)
        grid = self.grid
        start = grid.bounds(edit.measures[0])[0]
        end = grid.bounds(edit.measures[-1])[1]
        inside, outside = [], []
        for event in events:
            first = Fraction(event["offset"])
            if start <= first < end:
                inside.append(event)
            elif first < start < first + Fraction(event["duration"]):
                raise ValueError(
                    f"{event['id']} runs into measure {edit.measures[0]}; split it at the "
                    "barline first"
                )
            else:
                outside.append(event)
        total = sum(Fraction(item.duration) for item in edit.events)
        if total != end - start:
            raise ValueError(
                f"New events last {total} quarters but measures {edit.measures[0]}-"
                f"{edit.measures[-1]} hold {end - start}"
            )
        self._fresh([item.id for item in edit.events], {e["id"] for e in inside})
        cursor, passage = start, []
        for item in edit.events:
            passage.append({**item.model_dump(), "offset": str(cursor)})
            cursor += Fraction(item.duration)
        events[:] = sorted(outside + passage, key=lambda e: Fraction(e["offset"]))

    def transpose(self, edit: TransposeEdit):
        events = self._track(edit.track_id)
        step = interval.Interval(edit.interval)
        grid = self.grid
        chosen = set(edit.measures) if edit.measures else None
        for event in events:
            if not event["pitches"]:
                continue
            if chosen is not None:
                span = set(
                    grid.span(
                        Fraction(event["offset"]),
                        Fraction(event["offset"]) + Fraction(event["duration"]),
                    )
                )
                if not span & chosen:
                    continue
                if not span <= chosen:
                    raise ValueError(
                        f"{event['id']} extends beyond the transposed measures; include all "
                        "of its measures or split it first"
                    )
            moved = []
            for value in event["pitches"]:
                result = pitch.Pitch(value).transpose(step).nameWithOctave
                try:
                    moved.append(spelled_pitch(result))
                except ValueError as exc:
                    raise ValueError(
                        f"{value} in {event['id']} becomes {result}, which Skitz cannot store"
                    ) from exc
            event["pitches"] = moved

    def set_tempo(self, edit: TempoEdit):
        self.tempo_map = _set_change(self.tempo_map, TempoChange, edit.measure, "bpm", edit.bpm)

    def set_meter(self, edit: MeterEdit):
        self.meter_map = _set_change(self.meter_map, MeterChange, edit.measure, "meter", edit.meter)

    def result(self) -> Score:
        return Score(
            title=self.score.title,
            key=self.score.key,
            meter_map=tuple(self.meter_map),
            tempo_map=tuple(self.tempo_map),
            tracks=tuple(
                Track(
                    id=track.id,
                    name=track.name,
                    program=track.program,
                    events=tuple(Event.model_validate(e) for e in self.tracks[track.id]),
                )
                for track in self.score.tracks
            ),
        )


def apply_edits(score: Score, edits: list, protected: set[str]) -> Score:
    """Apply edits in order and return the new score. Raises ValueError on the first problem."""
    working = _Working(score, protected)
    for index, edit in enumerate(EDITS.validate_python(edits)):
        try:
            getattr(working, edit.op)(edit)
        except ValueError as exc:
            raise ValueError(f"Edit {index + 1} ({edit.op}): {exc}") from None
    return working.result()
