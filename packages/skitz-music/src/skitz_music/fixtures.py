"""Authored test material. These fixtures are not model compositions or benchmark results."""

from .score import Event, Score, Track


def chorale_fixture() -> Score:
    pitches = {
        "soprano": ["G4", "A4", "B-4", "A4", "F#4", "G4"],
        "alto": ["D4", "D4", "G4", "E-4", "D4", "D4"],
        "tenor": ["B-3", "F#3", "D4", "C4", "A3", "B-3"],
        "bass": ["G2", "D3", "G2", "C3", "D3", "G2"],
    }
    return Score(
        title="Skitz verification phrase",
        tracks=tuple(
            Track(
                id=voice,
                name=voice.title(),
                program=19,
                events=tuple(
                    Event(
                        id=f"{voice}_{i + 1:03}", offset=str(i * 3), duration="3", pitches=(value,)
                    )
                    for i, value in enumerate(notes)
                ),
            )
            for voice, notes in pitches.items()
        ),
    )


def progression_fixture() -> Score:
    """Chords, a melody, ties, rests, articulations and meter/tempo changes at barlines."""
    chords = [
        ("c1", "0", "2", ("C4", "E4", "G4"), "start", None),
        ("c2", "2", "2", ("C4", "E4", "G4"), "stop", None),
        ("c3", "4", "3", ("F3", "A3", "C4"), None, None),
        ("c4", "7", "1", (), None, None),
        ("c5", "8", "3", ("G3", "B3", "D4", "F4"), None, None),
        ("c6", "11", "3", ("C4", "E4", "G4"), None, "tenuto"),
    ]
    melody = [
        ("n01", "0", "1", ("E5",), None, None),
        ("n02", "1", "1", ("D5",), None, None),
        ("n03", "2", "3/2", ("C5",), None, None),
        ("n04", "7/2", "1/2", ("D5",), None, None),
        ("n05", "4", "1", ("A4",), None, None),
        ("n06", "5", "1", ("C5",), None, None),
        ("n07", "6", "2", ("F5",), None, None),
        ("n08", "8", "1", ("G5",), None, "staccato"),
        ("n09", "9", "1", ("F5",), None, None),
        ("n10", "10", "1", ("D5",), None, None),
        ("n11", "11", "3", ("C5",), None, "accent"),
    ]
    return Score(
        title="Skitz progression fixture",
        key="C major",
        meter_map=({"measure": 1, "meter": "4/4"}, {"measure": 3, "meter": "3/4"}),
        tempo_map=({"measure": 1, "bpm": 96}, {"measure": 3, "bpm": 120}),
        tracks=tuple(
            Track(
                id=track_id,
                name=name,
                program=program,
                events=tuple(
                    Event(
                        id=event_id,
                        offset=offset,
                        duration=duration,
                        pitches=pitches,
                        tie=tie,
                        articulation=articulation,
                    )
                    for event_id, offset, duration, pitches, tie, articulation in events
                ),
            )
            for track_id, name, program, events in (
                ("melody", "Flute", 73, melody),
                ("chords", "Piano", 0, chords),
            )
        ),
    )
