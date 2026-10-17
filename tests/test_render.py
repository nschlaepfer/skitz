import json
import shutil
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from music21 import chord, converter, meter, tempo
from skitz_music import Event, Project, Score, Track
from skitz_music.fixtures import chorale_fixture, progression_fixture
from skitz_music.importers import import_notation
from skitz_music.render import lily_durations, lilypond_source, render_score, restricted_run


def test_midi_and_musicxml_are_parseable_and_manifest_matches(tmp_path):
    score = chorale_fixture()
    report = render_score(score, tmp_path, audio=False, engrave=False)
    output = Path(report["output_directory"])
    assert report["status"] == "passed"
    for name in ("score.mid", "score.musicxml"):
        parsed = converter.parse(output / name)
        assert len(parsed.parts) == 4
        assert len(parsed.recurse().notes) == 24
    assert json.loads((output / "manifest.json").read_text())["revision"] == score.revision
    assert lilypond_source(score).count("\\new Staff <<") == 2


def musical_content(score):
    return (
        score.meter_map,
        score.tempo_map,
        score.key,
        [
            (t.name, t.program, [e.model_dump(exclude={"id"}) for e in t.events])
            for t in score.tracks
        ],
    )


def test_musicxml_round_trip_keeps_chords_maps_ties_and_articulations(tmp_path):
    score = progression_fixture()
    report = render_score(score, tmp_path, audio=False, engrave=False)
    output = Path(report["output_directory"])
    assert report["status"] == "passed"
    imported = import_notation(output / "score.musicxml")
    assert musical_content(imported) == musical_content(score)
    assert imported.title == score.title


def test_midi_carries_chords_and_maps(tmp_path):
    report = render_score(progression_fixture(), tmp_path, audio=False, engrave=False)
    parsed = converter.parse(Path(report["output_directory"]) / "score.mid")
    flat = parsed.flatten()
    meters = {
        (m.ratioString, float(m.offset)) for m in flat.getElementsByClass(meter.TimeSignature)
    }
    assert meters == {("4/4", 0.0), ("3/4", 8.0)}
    tempi = {(m.number, float(m.offset)) for m in flat.getElementsByClass(tempo.MetronomeMark)}
    assert tempi == {(96, 0.0), (120, 8.0)}
    chords = [c for c in flat.getElementsByClass(chord.Chord) if len(c.pitches) == 4]
    assert [p.nameWithOctave for p in chords[0].pitches] == ["G3", "B3", "D4", "F4"]


def test_lilypond_spells_chords_note_values_and_changes():
    source = lilypond_source(progression_fixture())
    assert "\\time 4/4" in source and "\\tempo 4 = 96" in source
    assert source.count("\\time 3/4") == 2 and source.count("\\tempo 4 = 120") == 2
    assert "<c' e' g'>2~ <c' e' g'>2 |" in source
    assert "<g b d' f'>2. |" in source
    assert "c''4. d''8 |" in source
    assert "<c' e' g'>2.-- |" in source and "g''4-." in source


def test_lilypond_ties_events_across_barlines_and_meter_changes():
    score = Score(
        meter_map=({"measure": 1, "meter": "3/4"}, {"measure": 2, "meter": "2/4"}),
        tracks=(
            Track(
                id="v",
                name="V",
                events=(
                    Event(id="a", offset="0", duration="2", pitch="C4"),
                    Event(id="b", offset="2", duration="3", pitch="D4", articulation="accent"),
                ),
            ),
        ),
    )
    source = lilypond_source(score)
    assert "c'2 d'4->~ | \\time 2/4 d'2 |" in source


def test_note_values_for_dotted_and_tuplet_lengths():
    assert lily_durations(Fraction(3)) == ["2."]
    assert lily_durations(Fraction(7, 2)) == ["2.."]
    assert lily_durations(Fraction(5)) == ["1", "4"]
    assert lily_durations(Fraction(1, 3)) == ["4*1/3"]


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("lilypond"), reason="macOS LilyPond required"
)
@pytest.mark.parametrize("fixture", [chorale_fixture, progression_fixture])
def test_real_engraving(tmp_path, fixture):
    report = render_score(fixture(), tmp_path, audio=False)
    assert report["status"] == "passed", report
    assert (Path(report["output_directory"]) / "score.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox required")
def test_renderer_cannot_read_private_file(tmp_path):
    private = tmp_path / "secret.txt"
    private.write_text("should-never-be-readable")
    work = tmp_path / "worker"
    work.mkdir()
    control = restricted_run(["/bin/echo", "sandbox-alive"], work)
    assert control["exit_code"] == 0
    assert "sandbox-alive" in control["diagnostics"]
    result = restricted_run(["/bin/cat", str(private)], work)
    assert result["exit_code"] != 0
    assert "should-never-be-readable" not in result["diagnostics"]


def test_rhythm_edits_survive_a_musicxml_round_trip(tmp_path):
    project = Project(tmp_path / "piece")
    project.create(progression_fixture(), ["chords"])
    project.apply_score_patch(
        project.read().revision,
        [
            {
                "op": "replace",
                "track_id": "melody",
                "measures": [2],
                "events": [
                    {"id": "n05", "duration": "1/2", "pitch": "A4"},
                    {"id": "x1", "duration": "1/2", "pitch": "B4"},
                    {"id": "x2", "duration": "1", "pitches": ["C5", "E5"]},
                    {"id": "x3", "duration": "2", "pitch": "F5", "tie": "start"},
                ],
            },
            {"op": "split", "event_id": "n08", "durations": ["1/2", "1/2"], "new_ids": ["x4"]},
            {"event_id": "n08", "set": {"pitch": "F5", "tie": "stop"}},
            {"op": "merge", "event_ids": ["n09", "n10"]},
            {"op": "transpose", "track_id": "melody", "interval": "-M2", "measures": [4]},
            {"op": "set_tempo", "measure": 4, "bpm": 132},
        ],
        [2, 3, 4],
    )
    edited = project.read()
    report = render_score(edited, tmp_path / "renders", audio=False, engrave=False)
    imported = import_notation(Path(report["output_directory"]) / "score.musicxml")
    assert musical_content(imported) == musical_content(edited)
