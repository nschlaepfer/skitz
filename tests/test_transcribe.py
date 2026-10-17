import json
import os
import shutil
import sys
import textwrap
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from skitz_music import samples, transcribe
from skitz_music.analysis import validate_score
from skitz_music.samples_cli import main as samples_main
from skitz_music.score import Event, Score, Track
from skitz_music.store import Project
from skitz_music.transcribe import GridNote, Note

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

RATE = samples.SAMPLE_RATE
BPM = 120
BEAT = 60 / BPM

# (offset, duration) in quarters and MIDI pitch: three bars of 4/4 in F major, with an
# eighth-note pair, a rest, a note tied over the bar line and two sixteenths.
MELODY = [
    (0, 1, 65), (1, 1, 69), (2, 0.5, 70), (2.5, 0.5, 69), (3, 1, 67),
    (4, 2, 65), (7, 2, 72),
    (9, 0.25, 74), (9.25, 0.25, 72), (9.5, 0.5, 70), (10, 1, 69), (11, 1, 65),
]  # fmt: skip
# What a transcription of MELODY should say, padded with a rest bar to the audio's end.
EXPECTED = [
    ("0", "1", "F4", None), ("1", "1", "A4", None), ("2", "1/2", "B-4", None),
    ("5/2", "1/2", "A4", None), ("3", "1", "G4", None),
    ("4", "2", "F4", None), ("6", "1", None, None), ("7", "1", "C5", "start"),
    ("8", "1", "C5", "stop"), ("9", "1/4", "D5", None), ("37/4", "1/4", "C5", None),
    ("19/2", "1/2", "B-4", None), ("10", "1", "A4", None), ("11", "1", "F4", None),
    ("12", "4", None, None),
]  # fmt: skip

FAKE = textwrap.dedent(
    """
    # Stand-in for basic-pitch: finds the sine-tone notes in the WAV Skitz hands it and
    # writes them the way basic-pitch does (unsorted rows, pitch-bend columns), each with
    # a quiet overtone an octave up, as the real model often reports.
    import csv, json, os, pathlib, sys, wave
    import numpy as np
    args = sys.argv[1:]
    out, audio = pathlib.Path(args[-2]), pathlib.Path(args[-1])
    if os.environ.get("FAKE_TRANSCRIBER_ARGS"):
        pathlib.Path(os.environ["FAKE_TRANSCRIBER_ARGS"]).write_text(json.dumps(args))
    with wave.open(str(audio)) as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
        pcm = np.frombuffer(frames, "<i2").reshape(-1, handle.getnchannels())
    mono = pcm.mean(axis=1) / 32768
    hop = 128
    energy = np.sqrt(np.convolve(mono**2, np.ones(hop) / hop, "same"))[::hop]
    edges = np.flatnonzero(np.diff(np.concatenate([[0], (energy > 0.02).astype(int), [0]])))
    rows = []
    for start, end in zip(edges[::2], edges[1::2]):
        a, b = start * hop, end * hop
        spectrum = np.abs(np.fft.rfft(mono[a:b] * np.hanning(b - a), 1 << 18))
        midi = int(round(69 + 12 * np.log2(np.argmax(spectrum) * rate / (1 << 18) / 440)))
        rows.append([a / rate, b / rate, midi, 100, 0, 1])
        rows.append([a / rate + 0.02, b / rate - 0.01, midi + 12, 30])
    with open(out / f"{audio.stem}_basic_pitch.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["start_time_s", "end_time_s", "pitch_midi", "velocity", "pitch_bend"])
        writer.writerows(reversed(rows))
    (out / f"{audio.stem}_basic_pitch.mid").write_bytes(b"MThd")
    """
)


def tones(melody, seconds: float, start: float = 0.0, harmonics: int = 1, decay: float = 0):
    """Sine (or harmonic) tones; each stops 20 ms early so the next one is a new onset."""
    audio = np.zeros(int(seconds * RATE), dtype=np.float32)
    for offset, length, midi in melody:
        frequency = 440 * 2 ** ((midi - 69) / 12)
        t = np.arange(int((length * BEAT - 0.02) * RATE)) / RATE
        tone = sum(np.sin(2 * np.pi * frequency * k * t) / k for k in range(1, harmonics + 1))
        envelope = np.minimum(1, t / 0.005) * np.minimum(1, (t[-1] - t) / 0.005)
        begin = int((start + offset * BEAT) * RATE)
        audio[begin : begin + len(t)] += (0.3 * tone * envelope * np.exp(-t * decay)).astype(
            np.float32
        )
    return np.stack([audio, audio], axis=1)


def events_of(score: Score, track: int = 0) -> list[tuple]:
    return [(e.offset, e.duration, e.pitch, e.tie) for e in score.tracks[track].events]


def notes_of(score: Score) -> list[tuple[Fraction, Fraction, str]]:
    """(onset, length, pitch) with tied events joined."""
    notes = []
    for event in score.tracks[0].events:
        if event.pitch is None:
            continue
        if event.tie in ("continue", "stop"):
            onset, length, name = notes[-1]
            notes[-1] = (onset, length + Fraction(event.duration), name)
        else:
            notes.append((Fraction(event.offset), Fraction(event.duration), event.pitch))
    return notes


@pytest.fixture
def fake_transcriber(tmp_path, monkeypatch):
    script = tmp_path / "fake_basic_pitch.py"
    script.write_text(FAKE)
    monkeypatch.setenv("SKITZ_TRANSCRIBER", f"{sys.executable} {script}")
    monkeypatch.setenv("FAKE_TRANSCRIBER_ARGS", str(tmp_path / "fake-args.json"))
    return tmp_path / "fake-args.json"


@pytest.fixture
def vocal_stem(tmp_path):
    """MELODY as a vocals stem written by `skitz samples stems` from a 120 BPM Suno clip."""
    folder = tmp_path / "stems/song"
    source = folder / "vocals.wav"
    samples.write_wav(source, tones(MELODY, 7.0))  # 14 quarters, so the score has 4 bars
    (folder / "separate-manifest.json").write_text(json.dumps({"bpm": BPM}))
    return source


def test_vocal_stem_becomes_an_editable_score(fake_transcriber, vocal_stem, tmp_path):
    result = transcribe.transcribe(vocal_stem, tmp_path / "projects/song-vocals")
    score = Project(tmp_path / "projects/song-vocals").read()
    assert validate_score(score)["status"] == "passed"
    assert events_of(score) == EXPECTED
    assert (score.meter, score.tempo, score.tracks[0].id, score.tracks[0].program) == (
        "4/4", 120, "vocals", 53,
    )  # fmt: skip
    assert score.key in {"F major", "D minor"}
    assert result["measures"] == 4 and result["bpm_source"] == "recorded"
    # Every overtone was dropped: one above the vocal range, the rest as chord tones.
    assert result["notes"]["kept"] == len(MELODY)
    assert result["notes"]["dropped"] == {"out_of_range": 1, "chord": len(MELODY) - 1}
    assert result["onset_shift"]["max_ms"] < 10
    args = json.loads(fake_transcriber.read_text())
    assert {"--save-note-events", "--save-midi"} <= set(args)
    assert args[args.index("--midi-tempo") + 1] == "120.0"
    assert args[args.index("--minimum-note-length") + 1] == "93.8"  # 3/4 of a sixteenth

    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["source"]["sha256"] == samples.sha256(vocal_stem)
    assert manifest["model"]["name"] == "basic-pitch"
    assert manifest["model"]["version"] == transcribe.BASIC_PITCH_VERSION
    assert manifest["tempo"]["bpm_source"] == "recorded"
    assert manifest["quantization"]["step_quarters"] == "1/4"
    assert manifest["quantization"]["score_start_seconds"] == 0.0
    assert manifest["reduction"]["line"] == "loudest"
    assert manifest["score"]["revision"] == score.revision
    assert Path(manifest["raw"]["note_events"]).is_file()


def test_downbeats_set_tempo_offset_and_meter(fake_transcriber, tmp_path):
    waltz = [(0, 1, 67), (1, 1, 69), (2, 1, 71), (3, 3, 72)]
    source = tmp_path / "piano.wav"
    samples.write_wav(source, tones(waltz, 4.0, start=0.5))
    beats = tmp_path / "beats.json"
    beats.write_text(
        json.dumps({"clip_id": "clip-1", "bpm": 120.0, "first_downbeat": 0.5, "beats_per_bar": 3})
    )
    result = transcribe.transcribe(source, tmp_path / "waltz", downbeats=beats)
    score = Project(tmp_path / "waltz").read()
    assert score.meter == "3/4" and score.tracks[0].id == "piano"
    assert events_of(score) == [
        ("0", "1", "G4", None), ("1", "1", "A4", None), ("2", "1", "B4", None),
        ("3", "3", "C5", None), ("6", "3", None, None),
    ]  # fmt: skip
    assert result["score_start_seconds"] == 0.5
    assert result["warnings"] == []


def test_raw_suno_downbeats_are_read(tmp_path):
    beats = tmp_path / "beats.json"
    beats.write_text(json.dumps({"downbeats": [[0.25 + 0.5 * i, i % 3 + 1] for i in range(12)]}))
    info = transcribe.read_downbeats(beats)
    assert (info["bpm"], info["first_downbeat"], info["beats_per_bar"]) == (120.0, 0.25, 3)


def test_notes_before_the_first_downbeat_become_a_pickup(fake_transcriber, tmp_path):
    source = tmp_path / "lead.wav"
    # A pickup on beat 4, then the downbeat one second (two beats) in.
    samples.write_wav(source, tones([(0, 1, 67), (1, 2, 72)], 3.0, start=0.5))
    result = transcribe.transcribe(source, tmp_path / "pickup", bpm=BPM, offset=1.0)
    score = Project(tmp_path / "pickup").read()
    assert score.tracks[0].id == "melody"
    assert result["score_start_seconds"] == -1.0
    assert events_of(score) == [
        ("0", "3", None, None), ("3", "1", "G4", None), ("4", "2", "C5", None),
        ("6", "2", None, None),
    ]  # fmt: skip
    assert any("before the first downbeat" in w for w in result["warnings"])


def test_estimated_tempo_is_rounded_and_flagged(fake_transcriber, tmp_path, monkeypatch):
    source = tmp_path / "lead.wav"
    samples.write_wav(source, tones(MELODY, 7.0))
    monkeypatch.setattr(transcribe, "estimate_bpm", lambda audio: 119.6)
    result = transcribe.transcribe(source, tmp_path / "estimated")
    assert result["tempo"] == 120 and result["bpm_source"] == "estimated"
    assert any("estimated" in w for w in result["warnings"])
    assert events_of(Project(tmp_path / "estimated").read()) == EXPECTED


def test_melody_line_picks_by_line():
    chord = [
        GridNote(0, 4, 48, 90), GridNote(0, 4, 55, 80), GridNote(0, 4, 64, 85),
        GridNote(0, 4, 76, 20),  # a quiet overtone never wins
    ]  # fmt: skip
    pick = {line: transcribe.melody_line(chord, line)[0][0].midi for line in transcribe.LINES}
    assert pick == {"top": 64, "bottom": 48, "loudest": 48}
    _, leftover, counts = transcribe.melody_line(chord, "top")
    assert len(leftover) == 3 and counts["chord"] == 3


def test_melody_line_resolves_overlaps():
    held = GridNote(0, 8, 60, 100)
    overtone = GridNote(2, 4, 72, 40)  # quiet and inside the held note: left over
    successor = GridNote(6, 12, 62, 70)  # outlasts the held note: cuts it short
    kept, leftover, counts = transcribe.melody_line([held, overtone, successor], "top")
    assert kept == [GridNote(0, 6, 60, 100), successor]
    assert leftover == [overtone]
    assert counts == {"chord": 0, "overlap": 1, "truncated": 1}
    # A strong higher note inside a held one takes over the top line.
    kept, _, _ = transcribe.melody_line([held, GridNote(4, 6, 67, 90)], "top")
    assert kept == [GridNote(0, 4, 60, 100), GridNote(4, 6, 67, 90)]
    kept, _, _ = transcribe.melody_line([held, GridNote(4, 6, 67, 90)], "bottom")
    assert kept == [held]


def test_split_lines_peels_chords_into_tracks():
    notes = [
        GridNote(0, 4, 60, 90), GridNote(0, 4, 64, 90), GridNote(0, 4, 67, 90),
        GridNote(4, 8, 62, 90), GridNote(4, 8, 65, 90),
    ]  # fmt: skip
    lines, info = transcribe.split_lines(notes, "top", 2)
    assert [[n.midi for n in line] for line in lines] == [[67, 65], [64, 62]]
    assert info["dropped"] == {"chord": 1, "overlap": 0}
    lines, info = transcribe.split_lines(notes, "top", 4)
    assert len(lines) == 3 and info["dropped"] == {}


def test_overlapping_unisons_merge():
    notes = [GridNote(0, 4, 60, 80), GridNote(3, 6, 60, 100), GridNote(6, 8, 60, 90)]
    merged, joined = transcribe.merge_unisons(notes)
    assert merged == [GridNote(0, 6, 60, 100), GridNote(6, 8, 60, 90)] and joined == 1
    merged, joined = transcribe.merge_unisons(notes, join_repeats=True)
    assert merged == [GridNote(0, 8, 60, 100)] and joined == 2


def test_quantize_and_score_origin():
    step = 0.125  # sixteenths at 120 BPM
    snapped, too_short = transcribe.quantize(
        [Note(0.51, 0.74, 60, 90), Note(1.0, 1.04, 62, 90)], 0.0, step
    )
    assert snapped == [GridNote(4, 6, 60, 90)] and too_short == 1
    assert transcribe.onset_shift(snapped, step) == {
        "mean_ms": 10.0, "max_ms": 10.0, "grid_step_ms": 125.0,
    }  # fmt: skip
    bar = 2.0
    # Bar 1 starts on the first downbeat, or whole bars earlier for a pickup.
    assert transcribe.score_origin([Note(0.47, 1, 60, 90)], 0.5, bar, step) == 0.5
    assert transcribe.score_origin([Note(0.1, 1, 60, 90)], 0.5, bar, step) == -1.5
    assert transcribe.score_origin([Note(0.6, 1, 60, 90)], 4.5, bar, step) == 0.5


def test_line_events_fill_bars_and_tie_over_bar_lines():
    spell = transcribe.speller("C major")
    notes = [GridNote(1, 7, 60, 90), GridNote(8, 20, 64, 90)]
    events = transcribe.line_events("piano", notes, 4, 24, Fraction(1), spell)
    assert [(e.offset, e.duration, e.pitch, e.tie) for e in events] == [
        ("0", "1", None, None), ("1", "3", "C4", "start"), ("4", "3", "C4", "stop"),
        ("7", "1", None, None), ("8", "4", "E4", "start"), ("12", "4", "E4", "continue"),
        ("16", "4", "E4", "stop"), ("20", "4", None, None),
    ]  # fmt: skip
    score = Score(meter="4/4", key="C major", tracks=(Track(id="piano", name="P", events=events),))
    assert validate_score(score)["status"] == "passed"
    assert events[0].id == "piano_0001"


def test_speller_follows_the_key():
    assert transcribe.speller("F major")(70) == "B-4"
    assert transcribe.speller("D major")(66) == "F#4"
    assert transcribe.speller("D major")(73) == "C#5"
    assert transcribe.speller("E- major")(68) == "A-4"
    assert transcribe.speller("F# major")(65) == "E#4"  # the scale's own spelling
    assert transcribe.speller("G minor")(66) == "F#4"  # the raised 7th
    assert transcribe.speller("G minor")(63) == "E-4"
    assert transcribe.speller("C minor")(71) == "B4"
    assert transcribe.speller("C major")(61) == "C#4"
    assert transcribe.speller("G major")(60) == "C4"


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("stems/song/bass.wav", "bass"),
        ("Night Drive (Backing Vocals).mp3", "backing-vocals"),
        ("Each Other (Keys).wav", "keyboard"),
        ("stems/song/drums-kit/kick.wav", "kick"),
        ("mix.mp3", None),
    ],
)
def test_stem_is_read_from_the_file_name(name, stem):
    assert transcribe.infer_stem(Path(name)) == stem


def test_unpitched_and_bad_settings_are_rejected(tmp_path):
    drums = tmp_path / "drums.wav"
    samples.write_wav(drums, np.zeros((RATE, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="unpitched"):
        transcribe.transcribe(drums, tmp_path / "x")
    with pytest.raises(ValueError, match="grid"):
        transcribe.transcribe(drums, tmp_path / "x", stem="bass", grid=10)
    with pytest.raises(ValueError, match="line"):
        transcribe.transcribe(drums, tmp_path / "x", stem="bass", line="middle")
    # Checked against the score rules before the model runs (no transcriber is set up).
    for bad in ({"meter": "4/5"}, {"key": "H major"}, {"program": 200}, {"bpm": 400}):
        with pytest.raises(ValueError):
            transcribe.transcribe(drums, tmp_path / "x", stem="bass", **{"bpm": 120, **bad})
    with pytest.raises(ValueError, match="does not divide"):
        transcribe.transcribe(drums, tmp_path / "x", stem="bass", bpm=120, meter="7/8", grid=4)


def test_failures_leave_no_project(tmp_path, monkeypatch, vocal_stem):
    monkeypatch.setenv("SKITZ_TRANSCRIBER", f"{sys.executable} -c 'import sys; sys.exit(3)'")
    with pytest.raises(RuntimeError, match="basic-pitch failed"):
        transcribe.transcribe(vocal_stem, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    empty = tmp_path / "empty.py"
    empty.write_text(
        "import pathlib, sys\n"
        "out = pathlib.Path(sys.argv[-2])\n"
        "(out / 'x_basic_pitch.csv').write_text("
        "'start_time_s,end_time_s,pitch_midi,velocity,pitch_bend\\n')\n"
    )
    monkeypatch.setenv("SKITZ_TRANSCRIBER", f"{sys.executable} {empty}")
    with pytest.raises(ValueError, match="no notes"):
        transcribe.transcribe(vocal_stem, tmp_path / "silent")
    assert not (tmp_path / "silent").exists()


def test_cli_and_service(fake_transcriber, vocal_stem, tmp_path, capsys):
    out = tmp_path / "cli"
    assert samples_main(["transcribe", str(vocal_stem), "-o", str(out), "--grid", "8"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "created" and result["tracks"][0]["id"] == "vocals"
    # The two sixteenths are under half an eighth-note step, so they are dropped.
    assert result["notes"]["kept"] == len(MELODY) - 2
    assert result["notes"]["dropped"]["too_short"] >= 2
    assert samples_main(["transcribe", str(vocal_stem), "-o", str(out)]) == 1
    assert "already exists" in json.loads(capsys.readouterr().out)["error"]

    service = samples.SamplesService(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        service.samples_transcribe("stems/song/vocals.wav", "../outside")
    with pytest.raises(ValueError, match="escapes"):
        service.samples_transcribe("stems/song/vocals.wav", "p", downbeats="../beats.json")
    made = service.samples_transcribe(
        "stems/song/vocals.wav", "projects/v", tracks=2, key="F major"
    )
    # The overtones the melody line skipped make up the second track.
    assert made["key"] == "F major"
    assert [t["id"] for t in made["tracks"]] == ["vocals", "vocals-2"]


real = pytest.mark.skipif(
    not os.environ.get("SKITZ_REAL_TRANSCRIPTION"),
    reason="installs basic-pitch (~300 MB); set SKITZ_REAL_TRANSCRIPTION=1 to run the real model",
)


def assert_close(found: list, expected: list):
    """Pitches and onsets exact for 90% of notes; lengths within an eighth for 80%."""
    by_onset = {onset: (length, name) for onset, length, name in found}
    hits = [(by_onset[o], (length, name)) for o, length, name in expected if o in by_onset]
    pitched = [got for got, want in hits if got[1] == want[1]]
    assert len(pitched) >= 0.9 * len(expected), (found, expected)
    close = [got for got, want in hits if abs(got[0] - want[0]) <= Fraction(1, 2)]
    assert len(close) >= 0.8 * len(expected), (found, expected)
    assert len(found) <= 1.1 * len(expected)


@real
def test_real_model_transcribes_harmonic_tones(tmp_path):
    source = tmp_path / "lead.wav"
    samples.write_wav(source, tones(MELODY, 7.0, harmonics=4, decay=1.5))
    transcribe.transcribe(source, tmp_path / "project", bpm=BPM)
    assert_close(notes_of(Project(tmp_path / "project").read()), notes_of_expected())


def notes_of_expected():
    score = Score(
        meter="4/4",
        key="F major",
        tracks=(
            Track(
                id="melody",
                name="Melody",
                events=tuple(
                    Event(id=f"e{i}", offset=o, duration=d, pitch=p, tie=t)
                    for i, (o, d, p, t) in enumerate(EXPECTED)
                ),
            ),
        ),
    )
    return notes_of(score)


@real
def test_real_model_round_trips_a_rendered_score(tmp_path):
    from skitz_music.render import render_score
    from skitz_music.soundfonts import default_soundfont

    if not shutil.which("fluidsynth") or default_soundfont() is None:
        pytest.skip("needs FluidSynth and `skitz soundfont install`")
    original = Score(
        title="Round trip",
        meter="4/4",
        tempo=BPM,
        key="F major",
        tracks=(
            Track(
                id="piano",
                name="Piano",
                program=0,
                events=tuple(
                    Event(id=f"p{i}", offset=o, duration=d, pitch=p, tie=t)
                    for i, (o, d, p, t) in enumerate(EXPECTED)
                ),
            ),
        ),
    )
    render = render_score(original, tmp_path / "renders", audio=True, engrave=False)
    assert render["status"] == "passed", render["errors"]
    wav = Path(render["output_directory"]) / "score.wav"
    transcribe.transcribe(wav, tmp_path / "back", bpm=BPM, key="F major", stem="piano")
    assert_close(notes_of(Project(tmp_path / "back").read()), notes_of(original))
