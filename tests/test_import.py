import pytest
from music21 import chord, meter, note, stream, tie
from skitz_music.analysis import validate_score
from skitz_music.importers import import_notation


def test_abc_import_preserves_pitch_and_rhythm(tmp_path):
    abc = tmp_path / "phrase.abc"
    abc.write_text("X:1\nT:Phrase\nM:3/4\nL:1/4\nQ:1/4=90\nK:Gm\nGAB | c3 |\n")
    score = import_notation(abc)
    assert [c.model_dump() for c in score.meter_map] == [{"measure": 1, "meter": "3/4"}]
    assert [c.model_dump() for c in score.tempo_map] == [{"measure": 1, "bpm": 90}]
    assert [e.pitches for e in score.tracks[0].events] == [("G4",), ("A4",), ("B-4",), ("C5",)]
    assert [e.duration for e in score.tracks[0].events] == ["1", "1", "1", "3"]
    assert validate_score(score)["status"] == "passed"


def test_abc_chords_keep_every_note(tmp_path):
    abc = tmp_path / "chords.abc"
    abc.write_text("X:1\nM:3/4\nL:1/4\nK:C\n[CEG]3 | [FAc]2 z |\n")
    score = import_notation(abc)
    events = score.tracks[0].events
    assert [e.pitches for e in events] == [("C4", "E4", "G4"), ("F4", "A4", "C5"), ()]
    assert validate_score(score)["status"] == "passed"


@pytest.mark.parametrize(
    "body,match",
    [
        ("CDEF |\nM:3/4\nGAB |\n", "inside an ABC tune"),
        ("CDEF | [Q:1/4=120] GABc |\n", "inside an ABC tune"),
        ("CDEF |\nK:G\nGABc |\n", "inside an ABC tune"),
    ],
)
def test_abc_changes_music21_cannot_read_are_rejected(tmp_path, body, match):
    abc = tmp_path / "changes.abc"
    abc.write_text("X:1\nM:4/4\nL:1/4\nQ:1/4=100\nK:C\n" + body)
    with pytest.raises(ValueError, match=match):
        import_notation(abc)


def test_abc_pickup_is_rejected(tmp_path):
    abc = tmp_path / "pickup.abc"
    abc.write_text("X:1\nM:3/4\nL:1/4\nK:C\nG | c3 | d3 |\n")
    with pytest.raises(ValueError, match="Pickup"):
        import_notation(abc)


def written(tmp_path, *parts, name="piece.musicxml"):
    score = stream.Score()
    for part in parts:
        score.insert(0, part)
    path = tmp_path / name
    score.write("musicxml", fp=path)
    return path


def part_with(*items, meters=(("4/4", 0),)):
    part = stream.Part()
    for value, offset in meters:
        part.insert(offset, meter.TimeSignature(value))
    offset = 0
    for item in items:
        part.insert(offset, item)
        offset += item.quarterLength
    return part


def test_musicxml_meter_change_off_the_barline_is_rejected(tmp_path):
    path = written(
        tmp_path,
        part_with(*(note.Note("C4") for _ in range(8)), meters=(("4/4", 0), ("3/4", 2))),
    )
    with pytest.raises(ValueError):
        import_notation(path)


def test_musicxml_partially_tied_chord_is_rejected(tmp_path):
    first = chord.Chord(["C4", "E4"], quarterLength=2)
    first.notes[0].tie = tie.Tie("start")
    second = chord.Chord(["C4", "G4"], quarterLength=2)
    second.notes[0].tie = tie.Tie("stop")
    with pytest.raises(ValueError, match="tied differently"):
        import_notation(written(tmp_path, part_with(first, second)))


def test_musicxml_simultaneous_voices_are_rejected(tmp_path):
    measure = stream.Measure()
    measure.insert(0, meter.TimeSignature("4/4"))
    for pitch_name in ("C5", "C4"):
        voice = stream.Voice()
        voice.append(note.Note(pitch_name, quarterLength=4))
        measure.insert(0, voice)
    part = stream.Part()
    part.append(measure)
    with pytest.raises(ValueError, match="voices"):
        import_notation(written(tmp_path, part))
