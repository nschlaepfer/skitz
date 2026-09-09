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
                    Event(id=f"{voice}_{i + 1:03}", offset=str(i * 3), duration="3", pitch=value)
                    for i, value in enumerate(notes)
                ),
            )
            for voice, notes in pitches.items()
        ),
    )
