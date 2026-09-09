"""Structural validity and explicitly style-specific findings, never a taste score."""

from fractions import Fraction
from itertools import combinations

from music21 import note, pitch, voiceLeading

from .score import Score


def inspect_score(score: Score) -> dict:
    end = max(
        (Fraction(e.offset) + Fraction(e.duration) for t in score.tracks for e in t.events),
        default=Fraction(0),
    )
    return {
        "revision": score.revision,
        "title": score.title,
        "meter": score.meter,
        "tempo": score.tempo,
        "key": score.key,
        "duration_quarters": str(end),
        "measures": int(-(-end // score.bar_length)),
        "tracks": [
            {
                "id": t.id,
                "name": t.name,
                "event_count": len(t.events),
                "events": [e.model_dump() for e in t.events],
            }
            for t in score.tracks
        ],
    }


def validate_score(score: Score) -> dict:
    findings = []
    ends = []
    for track in score.tracks:
        events = sorted(track.events, key=lambda e: Fraction(e.offset))
        cursor = Fraction(0)
        for index, event in enumerate(events):
            start = Fraction(event.offset)
            end = start + Fraction(event.duration)
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
                and previous.pitch == event.pitch
                and Fraction(previous.offset) + Fraction(previous.duration) == start
            ):
                findings.append(
                    {"rule": "orphan_tie_stop", "event_ids": [event.id], "severity": "error"}
                )
            if event.tie in ("start", "continue") and not (
                following
                and following.tie in ("stop", "continue")
                and following.pitch == event.pitch
                and Fraction(following.offset) == end
            ):
                findings.append(
                    {"rule": "orphan_tie_start", "event_ids": [event.id], "severity": "error"}
                )
            cursor = max(cursor, end)
        ends.append(cursor)
        if not events or cursor % score.bar_length:
            findings.append({"rule": "incomplete_measure", "track": track.id, "severity": "error"})
    if len(set(ends)) > 1:
        findings.append({"rule": "unequal_track_lengths", "severity": "error"})
    return {
        "revision": score.revision,
        "status": "failed" if findings else "passed",
        "rule_set": "structure-v1",
        "findings": findings,
    }


def analyze_voice_leading(score: Score) -> dict:
    findings = []
    ranges = {"soprano": (60, 81), "alto": (55, 74), "tenor": (48, 69), "bass": (40, 60)}
    ordered = sorted(score.tracks, key=lambda t: list(ranges).index(t.id) if t.id in ranges else 4)
    timeline = sorted({Fraction(e.offset) for t in ordered for e in t.events})

    def active(track, time):
        return next(
            (
                e
                for e in track.events
                if Fraction(e.offset) <= time < Fraction(e.offset) + Fraction(e.duration)
            ),
            None,
        )

    for track in ordered:
        for event in track.events:
            if event.pitch and track.id in ranges:
                low, high = ranges[track.id]
                if not low <= pitch.Pitch(event.pitch).midi <= high:
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
            if not a or not b or a.pitch is None or b.pitch is None:
                previous = None
                continue
            if pitch.Pitch(a.pitch).ps < pitch.Pitch(b.pitch).ps:
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
                    note.Note(old_a.pitch),
                    note.Note(a.pitch),
                    note.Note(old_b.pitch),
                    note.Note(b.pitch),
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
        "limitations": "Ranges, crossings, and parallel fifths/octaves only; not a harmony or musical-quality grade.",
    }


def compare_revisions(before: Score, after: Score) -> dict:
    left, right = before.events_by_id(), after.events_by_id()
    changed = sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))
    metadata_changed = before.model_dump(exclude={"tracks"}) != after.model_dump(exclude={"tracks"})
    return {
        "before": before.revision,
        "after": after.revision,
        "changed_event_ids": changed,
        "metadata_changed": metadata_changed,
        "unchanged_tracks": [t.id for t in before.tracks if t in after.tracks],
    }
