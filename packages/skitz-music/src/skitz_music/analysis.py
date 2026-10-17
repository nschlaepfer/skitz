"""Structural validity and explicitly style-specific findings, never a taste score."""

from fractions import Fraction
from itertools import combinations

from music21 import note, pitch, voiceLeading

from .score import Score


def inspect_score(score: Score) -> dict:
    grid = score.grid
    end = score.end
    count = grid.count(end)
    return {
        "revision": score.revision,
        "schema_version": score.schema_version,
        "title": score.title,
        "key": score.key,
        "meter_map": [change.model_dump() for change in score.meter_map],
        "tempo_map": [change.model_dump() for change in score.tempo_map],
        "duration_quarters": str(end),
        "measures": count,
        "measure_grid": [
            {
                "measure": number,
                "start": str(grid.bounds(number)[0]),
                "end": str(grid.bounds(number)[1]),
                "meter": grid.meter(number),
                "bpm": score.tempo_at(number),
            }
            for number in range(1, count + 1)
        ],
        "tracks": [
            {
                "id": t.id,
                "name": t.name,
                "program": t.program,
                "event_count": len(t.events),
                "events": [
                    {
                        **e.model_dump(mode="json"),
                        "measures": [grid.span(e.start, e.end)[0], grid.span(e.start, e.end)[-1]],
                    }
                    for e in t.events
                ],
            }
            for t in score.tracks
        ],
    }


def validate_score(score: Score) -> dict:
    findings = []
    ends = []
    grid = score.grid
    for track in score.tracks:
        events = sorted(track.events, key=lambda e: e.start)
        cursor = Fraction(0)
        for index, event in enumerate(events):
            start = event.start
            end = event.end
            if start != cursor:
                findings.append(
                    {
                        "rule": "overlap" if start < cursor else "implicit_gap",
                        "track": track.id,
                        "event_ids": [event.id],
                        "severity": "error",
                    }
                )
            previous = events[index - 1] if index else None
            following = events[index + 1] if index + 1 < len(events) else None
            if event.tie in ("stop", "continue") and not (
                previous
                and previous.tie in ("start", "continue")
                and previous.pitches == event.pitches
                and previous.end == start
            ):
                findings.append(
                    {"rule": "orphan_tie_stop", "event_ids": [event.id], "severity": "error"}
                )
            if event.tie in ("start", "continue") and not (
                following
                and following.tie in ("stop", "continue")
                and following.pitches == event.pitches
                and following.start == end
            ):
                findings.append(
                    {"rule": "orphan_tie_start", "event_ids": [event.id], "severity": "error"}
                )
            cursor = max(cursor, end)
        ends.append(cursor)
        if not events or not grid.is_boundary(cursor):
            findings.append(
                {
                    "rule": "incomplete_measure",
                    "track": track.id,
                    "offset": str(cursor),
                    "severity": "error",
                }
            )
    if len(set(ends)) > 1:
        findings.append({"rule": "unequal_track_lengths", "severity": "error"})
    last_measure = max(grid.count(max(ends, default=Fraction(0))), 1)
    for name, changes in (("meter_map", score.meter_map), ("tempo_map", score.tempo_map)):
        for change in changes:
            if change.measure > last_measure:
                findings.append(
                    {
                        "rule": "map_change_beyond_end",
                        "map": name,
                        "measure": change.measure,
                        "severity": "error",
                    }
                )
    return {
        "revision": score.revision,
        "status": "failed" if findings else "passed",
        "rule_set": "structure-v2",
        "findings": findings,
    }


def analyze_voice_leading(score: Score) -> dict:
    findings = []
    ranges = {"soprano": (60, 81), "alto": (55, 74), "tenor": (48, 69), "bass": (40, 60)}
    ordered = sorted(score.tracks, key=lambda t: list(ranges).index(t.id) if t.id in ranges else 4)
    timeline = sorted({e.start for t in ordered for e in t.events})

    def active(track, time):
        return next((e for e in track.events if e.start <= time < e.end), None)

    for track in ordered:
        for event in track.events:
            if event.pitches and track.id in ranges:
                low, high = ranges[track.id]
                if not all(low <= pitch.Pitch(p).midi <= high for p in event.pitches):
                    findings.append(
                        {
                            "rule": "voice_range",
                            "voices": [track.id],
                            "event_ids": [event.id],
                            "severity": "warning",
                        }
                    )
    for upper, lower in combinations(ordered, 2):
        previous = None
        for time in timeline:
            a, b = active(upper, time), active(lower, time)
            # Crossings and parallels compare single notes; chords and rests reset the motion.
            if not a or not b or len(a.pitches) != 1 or len(b.pitches) != 1:
                previous = None
                continue
            if pitch.Pitch(a.pitches[0]).ps < pitch.Pitch(b.pitches[0]).ps:
                findings.append(
                    {
                        "rule": "voice_crossing",
                        "voices": [upper.id, lower.id],
                        "event_ids": [a.id, b.id],
                        "offset": str(time),
                        "severity": "warning",
                    }
                )
            if previous:
                old_a, old_b = previous
                quartet = voiceLeading.VoiceLeadingQuartet(
                    note.Note(old_a.pitches[0]),
                    note.Note(a.pitches[0]),
                    note.Note(old_b.pitches[0]),
                    note.Note(b.pitches[0]),
                )
                for rule, detected in (
                    ("parallel_perfect_fifth", quartet.parallelFifth()),
                    ("parallel_octave", quartet.parallelOctave()),
                ):
                    if detected:
                        findings.append(
                            {
                                "rule": rule,
                                "voices": [upper.id, lower.id],
                                "from_event_ids": [old_a.id, old_b.id],
                                "to_event_ids": [a.id, b.id],
                                "offset": str(time),
                                "severity": "warning",
                            }
                        )
            previous = a, b
    return {
        "revision": score.revision,
        "rule_set": "chorale-v1",
        "status": "findings" if findings else "clear",
        "findings": findings,
        "limitations": (
            "Ranges, crossings, and parallel fifths/octaves only; not a harmony or "
            "musical-quality grade. Chords are range-checked; crossings and parallels "
            "compare single-note events between tracks."
        ),
    }


def changed_measures(before: Score, after: Score) -> list[int]:
    """Every measure whose events, barlines, meter or tempo differ between two scores."""
    old, new = before.grid, after.grid
    touched: set[int] = set()
    left, right = before.events_by_id(), after.events_by_id()
    for event_id in left.keys() | right.keys():
        if left.get(event_id) == right.get(event_id):
            continue
        for grid, entry in ((old, left.get(event_id)), (new, right.get(event_id))):
            if entry:
                touched.update(grid.span(entry[1].start, entry[1].end))
    count = max(old.count(before.end), new.count(after.end))
    for number in range(1, count + 1):
        if (
            old.bounds(number) != new.bounds(number)
            or old.meter(number) != new.meter(number)
            or before.tempo_at(number) != after.tempo_at(number)
            or (before.title, before.key) != (after.title, after.key)
        ):
            touched.add(number)
    return sorted(touched)


def compare_revisions(before: Score, after: Score) -> dict:
    left, right = before.events_by_id(), after.events_by_id()
    changed = sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))
    metadata_changed = before.model_dump(exclude={"tracks"}) != after.model_dump(exclude={"tracks"})
    return {
        "before": before.revision,
        "after": after.revision,
        "changed_event_ids": changed,
        "added_event_ids": sorted(right.keys() - left.keys()),
        "removed_event_ids": sorted(left.keys() - right.keys()),
        "changed_measures": changed_measures(before, after),
        "metadata_changed": metadata_changed,
        "unchanged_tracks": [t.id for t in before.tracks if t in after.tracks],
    }
