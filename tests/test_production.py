"""Analysis, fitting, effects and DAW export, checked on synthesized audio of known
tempo, key and chords."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from music21 import midi as m21midi
from skitz_music import samples
from skitz_music.samples_cli import main as samples_main

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
needs_fx = pytest.mark.skipif(
    importlib.util.find_spec("pedalboard") is None, reason="needs pedalboard (fx extra)"
)

RATE = samples.SAMPLE_RATE
C, Am, F, G = [36, 48, 52, 55], [45, 57, 60, 64], [41, 53, 57, 60], [43, 55, 59, 62]
Dm, E = [38, 50, 53, 57], [40, 52, 56, 59]


def stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono], axis=1).astype(np.float32)


def sine(hz: float, seconds: float, level: float = 0.5) -> np.ndarray:
    return stereo(level * np.sin(2 * np.pi * hz * np.arange(int(seconds * RATE)) / RATE))


def chords(progression: list[list[int]], bpm: float, beats_per_bar: int = 4) -> np.ndarray:
    """One plucked chord per bar: MIDI notes with six decaying harmonics, bass first."""
    t = np.arange(int(beats_per_bar * 60 / bpm * RATE)) / RATE
    envelope = np.exp(-t * 1.5) * np.minimum(1, t / 0.01)
    bars = []
    for chord in progression:
        bar = np.zeros_like(t)
        for voice, note in enumerate(chord):
            hz = 440 * 2 ** ((note - 69) / 12)
            for harmonic in range(1, 7):
                bar += np.sin(2 * np.pi * hz * harmonic * t) / harmonic**1.5 * (1.5 - (voice > 0))
        bars.append(bar * envelope)
    audio = np.concatenate(bars)
    return stereo(audio / np.abs(audio).max() * 0.5)


def clicks(bpm: float, seconds: float, offset: float = 0.0) -> np.ndarray:
    """Decaying 80 Hz thump on every beat."""
    audio = np.zeros((int(seconds * RATE), 2), dtype=np.float32)
    t = np.arange(int(0.15 * RATE)) / RATE
    hit = (np.sin(2 * np.pi * 80 * t) * np.exp(-t * 30) * 0.8).astype(np.float32)
    at = offset
    while at < seconds:
        start = int(at * RATE)
        piece = hit[: len(audio) - start]
        audio[start : start + len(piece)] += piece[:, None]
        at += 60 / bpm
    return audio


def peak_hz(audio: np.ndarray) -> float:
    mono = audio.mean(axis=1)
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    return float(np.fft.rfftfreq(len(mono), 1 / RATE)[np.argmax(spectrum)])


def band_db(audio: np.ndarray, low: float, high: float) -> float:
    spectrum = np.abs(np.fft.rfft(audio.mean(axis=1))) ** 2
    freqs = np.fft.rfftfreq(len(audio), 1 / RATE)
    return 10 * np.log10(spectrum[(freqs >= low) & (freqs < high)].mean())


def manifest(directory, operation):
    return json.loads((directory / f"{operation}-manifest.json").read_text())


def song(tmp_path, progression, bpm=120, name="song.wav", drums=True):
    audio = chords(progression * 2, bpm)
    if drums:
        audio = audio + clicks(bpm, len(audio) / RATE) * 0.5
    path = tmp_path / name
    samples.write_wav(path, audio)
    return path


@pytest.mark.parametrize("bpm", [90, 120, 174])
@pytest.mark.parametrize("offset", [0.0, 0.3])
def test_tempo_estimate_finds_bpm_and_first_beat(bpm, offset):
    tempo = samples.estimate_tempo(clicks(bpm, 12, offset))
    assert tempo["estimate"] is True
    assert tempo["bpm"] == pytest.approx(bpm, abs=0.5)
    assert tempo["first_beat"] == pytest.approx(offset, abs=0.03)
    assert tempo["alternatives"] == [pytest.approx(bpm / 2, abs=0.5), pytest.approx(bpm * 2, abs=1)]


def test_analyze_estimates_key_chords_and_tempo(tmp_path):
    result = samples.analyze(song(tmp_path, [C, Am, F, G]))
    assert result["estimate"] is True and "not by listening" in result["note"]
    assert all(result[part]["estimate"] is True for part in ("tempo", "key", "chords"))
    assert result["tempo"]["bpm"] == pytest.approx(120, abs=1)
    assert result["key"]["key"] == "C major"
    assert result["key"]["camelot"] == "8B"
    assert result["chords"]["progression"] == ["C", "Am", "F", "G"] * 2
    first = result["chords"]["segments"][1]
    assert (first["chord"], first["root"], first["quality"]) == ("Am", "A", "minor")
    assert first["start"] == pytest.approx(2.0) and first["bar"] == pytest.approx(1.0)
    assert result["chords"]["grid"]["bpm_from"] == "estimate"


def test_analyze_finds_a_minor_key(tmp_path):
    result = samples.analyze(song(tmp_path, [Am, Dm, E, Am]), bpm=120)
    assert result["key"]["key"] == "A minor"
    assert result["key"]["camelot"] == "8A"
    assert result["chords"]["progression"] == ["Am", "Dm", "E", "Am", "Dm", "E", "Am"]
    assert result["chords"]["grid"]["bpm_from"] == "argument"


def test_key_parsing_and_shifts():
    assert samples.parse_key("A minor") == samples.parse_key("am") == (9, "minor")
    assert samples.parse_key("Bb major") == samples.parse_key("bb") == (10, "major")
    assert samples.parse_key("F#m") == (6, "minor")
    assert samples.parse_key("8A") == (9, "minor") and samples.parse_key("8b") == (0, "major")
    assert samples.parse_key("Ebmin") == (3, "minor")
    with pytest.raises(ValueError, match="Unknown key"):
        samples.parse_key("H minor")
    assert samples.key_shift((9, "minor"), (0, "minor")) == (3, "same mode")
    assert samples.key_shift((7, "major"), (6, "major")) == (-1, "same mode")
    assert samples.key_shift((0, "major"), (9, "minor")) == (0, "relative")
    assert samples.key_shift((0, "major"), (6, "major"))[0] == -6
    assert {samples.camelot(t, m) for t in range(12) for m in ("major", "minor")} == {
        f"{n}{letter}" for n in range(1, 13) for letter in "AB"
    }


@needs_fx
@pytest.mark.parametrize("engine", ["pedalboard", "rubberband"])
def test_fit_changes_tempo_and_pitch_independently(tmp_path, engine):
    if engine == "rubberband" and not samples._ffmpeg_rubberband():
        pytest.skip("ffmpeg has no rubberband filter")
    tone = tmp_path / "a440.wav"
    beat = tmp_path / "beat100.wav"
    samples.write_wav(tone, sine(440, 3))
    samples.write_wav(beat, clicks(100, 8))

    up = samples.fit_sample(tone, tmp_path / "out", semitones=3, engine=engine)
    shifted = samples.decode(up["outputs"][0]["path"])
    assert len(shifted) == 3 * RATE
    assert peak_hz(shifted[RATE // 2 : -RATE // 2]) == pytest.approx(523.25, rel=0.01)

    faster = samples.fit_sample(beat, tmp_path / "out", bpm=120, source_bpm=100, engine=engine)
    stretched = samples.decode(faster["outputs"][0]["path"])
    assert len(stretched) == round(8 * RATE * 100 / 120)
    assert samples.estimate_tempo(stretched)["bpm"] == pytest.approx(120, abs=1)

    slow = samples.fit_sample(tone, tmp_path / "out", bpm=150, source_bpm=100, engine=engine)
    assert peak_hz(samples.decode(slow["outputs"][0]["path"])[RATE // 4 : -RATE // 4]) == (
        pytest.approx(440, rel=0.005)
    )
    settings = manifest(tmp_path / "out", "fit-beat100-120bpm")["settings"]
    assert settings["tempo_ratio"] == 1.2 and settings["length_ratio"] == pytest.approx(0.833333)
    assert settings["source_bpm_from"] == "argument" and settings["semitones"] == 0
    assert settings["engine"]["name"] == (
        "pedalboard" if engine == "pedalboard" else "ffmpeg-rubberband"
    )


@needs_fx
def test_fit_to_a_key_uses_the_estimated_source_key(tmp_path):
    source = song(tmp_path, [Am, Dm, E, Am], drums=False)
    result = samples.fit_sample(source, tmp_path / "fit", key="C minor")
    assert result["outputs"][0]["path"].endswith("song-Cm.wav")
    settings = manifest(tmp_path / "fit", "fit-song-Cm")["settings"]
    assert settings["source_key"] == "A minor" and settings["source_key_from"] == "estimate"
    assert settings["semitones"] == 3 and settings["pitch_ratio"] == pytest.approx(2 ** (3 / 12))
    assert settings["estimated"] == ["source_key"] and settings["key"] == "C minor"
    assert samples.analyze(result["outputs"][0]["path"])["key"]["key"] == "C minor"


@needs_fx
def test_fit_reads_the_recorded_bpm_and_records_the_new_one(tmp_path):
    folder = tmp_path / "songs/drums"
    clip = folder / "Drums-clip1.wav"
    samples.write_wav(clip, clicks(120, 8))
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "source": "suno",
                "request": {"skitz_bpm": 120},
                "files": [{"clip_id": "clip-1", "path": str(clip)}],
            }
        )
    )
    result = samples.fit_sample(clip, tmp_path / "fitted", bpm=96)
    settings = manifest(tmp_path / "fitted", "fit-Drums-clip1-96bpm")["settings"]
    assert settings["source_bpm"] == 120 and settings["source_bpm_from"] == "recorded"
    assert settings["estimated"] == []
    fitted = result["outputs"][0]["path"]
    assert samples.suno_bpm(Path(fitted)) == 96
    loops = samples.chop_loops(fitted, tmp_path / "loops")  # no bpm: read from the fit
    assert loops["count"] == 4  # 10 s at 96 BPM = 4 bars of 2.5 s


def test_fit_needs_a_target(tmp_path):
    tone = tmp_path / "tone.wav"
    samples.write_wav(tone, sine(440, 1))
    with pytest.raises(ValueError, match="target"):
        samples.fit_sample(tone, tmp_path)
    with pytest.raises(ValueError, match="not both"):
        samples.fit_sample(tone, tmp_path, key="C", semitones=2)
    with pytest.raises(ValueError, match="ratio"):
        samples.fit_sample(tone, tmp_path, bpm=600, source_bpm=100)
    with pytest.raises(ValueError, match="positive"):
        samples.fit_sample(tone, tmp_path, bpm=90, source_bpm=0)


@needs_fx
def test_fit_between_major_and_minor_uses_the_relative_key(tmp_path):
    source = song(tmp_path, [C, Am, F, G], drums=False)
    samples.fit_sample(source, tmp_path / "fit", key="D minor", source_key="C major")
    settings = manifest(tmp_path / "fit", "fit-song-Dm")["settings"]
    assert settings["semitones"] == 5 and settings["key_relation"] == "relative"
    assert settings["target_key"] == "D minor" and settings["key"] == "F major"


def test_chain_syntax_resolves_with_defaults():
    spec = samples.parse_chain(
        "hp=120/24,lowshelf=200/-3,peak=1000/-4/2,peak=3000/2,comp=-18/4,"
        "delay=0.75q/0.3/0.25,reverb=0.2,gain=-2,pan=-0.5,limit"
    )
    assert spec["highpass"] == {"hz": 120, "slope": 24}
    assert spec["peak"] == [{"hz": 1000, "db": -4, "q": 2}, {"hz": 3000, "db": 2}]
    assert spec["delay"] == {"beats": 0.75, "feedback": 0.3, "mix": 0.25}
    stages = samples.resolve_chain(spec, bpm=120)
    assert [s["effect"] for s in stages] == [
        "highpass", "low_shelf", "peak", "peak", "compress", "delay", "reverb", "gain_db",
        "pan", "limit",
    ]  # fmt: skip
    delay = next(s for s in stages if s["effect"] == "delay")
    assert delay["seconds"] == pytest.approx(0.375)
    assert stages[-1] == {"effect": "limit", "ceiling_db": -1, "release_ms": 100, "lookahead_ms": 5}
    assert samples.resolve_chain({"reverb": 0.3})[0]["wet"] == 0.3
    with pytest.raises(ValueError, match="needs bpm"):
        samples.resolve_chain("delay=0.5q")
    with pytest.raises(ValueError, match="Unknown effect"):
        samples.resolve_chain({"chorus": 1})
    with pytest.raises(ValueError, match="between"):
        samples.resolve_chain("pan=2")
    with pytest.raises(ValueError, match="slope"):
        samples.resolve_chain("hp=100/10")


@needs_fx
def test_filters_compressor_and_pan():
    noise = (np.random.default_rng(1).standard_normal((RATE * 2, 2)) * 0.1).astype(np.float32)
    high = samples.apply_chain(noise, samples.resolve_chain("hp=1000/24"))
    assert band_db(high, 250, 500) - band_db(noise, 250, 500) < -25
    assert abs(band_db(high, 4000, 8000) - band_db(noise, 4000, 8000)) < 1
    low = samples.apply_chain(noise, samples.resolve_chain("lp=1000/24"))
    assert band_db(low, 4000, 8000) - band_db(noise, 4000, 8000) < -40
    shelf = samples.apply_chain(noise, samples.resolve_chain("highshelf=4000/-6"))
    assert band_db(shelf, 8000, 16000) - band_db(noise, 8000, 16000) == pytest.approx(-6, abs=1)

    tone = sine(440, 2, level=0.9)
    squashed = samples.apply_chain(tone, samples.resolve_chain("comp=-30/10/1/50"))
    assert np.sqrt((squashed[RATE:] ** 2).mean()) < np.sqrt((tone[RATE:] ** 2).mean()) / 4
    left = samples.apply_chain(tone, samples.resolve_chain("pan=-1"))
    assert np.abs(left[:, 1]).max() == 0 and np.abs(left[:, 0]).max() == pytest.approx(0.9)


def test_limiter_is_a_brickwall_and_transparent_below_it():
    rng = np.random.default_rng(0)
    quiet = (rng.standard_normal((RATE, 2)) * 0.05).astype(np.float32)
    assert np.array_equal(samples.limit(quiet), quiet)
    hot = sine(110, 1, level=3.0) + quiet
    limited = samples.limit(hot, ceiling_db=-1)
    assert 20 * np.log10(np.abs(limited).max()) == pytest.approx(-1, abs=0.01)
    limited = samples.limit(hot, ceiling_db=-6)
    assert 20 * np.log10(np.abs(limited).max()) == pytest.approx(-6, abs=0.01)


@needs_fx
def test_layer_effects_master_and_manifest(tmp_path):
    hit = tmp_path / "hit.wav"
    pad = tmp_path / "pad.wav"
    burst = np.zeros((RATE // 2, 2), dtype=np.float32)
    burst[: RATE // 20] = sine(1000, 0.05, level=0.5)
    samples.write_wav(hit, burst)
    samples.write_wav(pad, sine(220, 1, level=0.6))
    out = tmp_path / "mix/out.wav"
    plan = [
        {"sample": str(hit), "at": 0, "unit": "beat", "pan": -1,
         "fx": {"delay": {"beats": 1, "feedback": 0, "mix": 0.5}}},
        {"sample": str(pad), "at": 1, "fx": "hp=100,reverb=0.3", "gain_db": 6},
    ]  # fmt: skip
    samples.layer(out, plan, bpm=120, bars=2, master={"compress": -12, "limit": True})
    mixed = samples.decode(out)

    def loudest(start: float, end: float, channel: int) -> float:
        return float(np.abs(mixed[int(start * RATE) : int(end * RATE), channel]).max())

    assert 20 * np.log10(np.abs(mixed).max()) <= -0.99  # the master limiter's ceiling
    assert loudest(0, 1.9, 1) == 0  # the hit is panned hard left
    assert loudest(0.1, 0.45, 0) < 0.01 and loudest(0.5, 0.56, 0) > 0.05  # echo one beat on
    assert loudest(3.1, 3.5, 1) > 0.001  # reverb rings on after the pad stops at 3 s
    settings = manifest(out.parent, "layer-out")["settings"]
    assert settings["tracks"] == {"hit": [1], "pad": [2]}
    assert settings["effects"][0]["pan"] == -1
    assert settings["effects"][0]["chain"][0] == {
        "effect": "delay", "seconds": 0.5, "beats": 1, "feedback": 0, "mix": 0.5,
    }  # fmt: skip
    assert [s["effect"] for s in settings["effects"][1]["chain"]] == ["highpass", "reverb"]
    assert [s["effect"] for s in settings["master"]] == ["compress", "limit"]
    assert settings["pedalboard"]


def test_gain_pan_and_limit_need_no_pedalboard(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pedalboard", None)
    hit = tmp_path / "hit.wav"
    samples.write_wav(hit, np.full((RATE // 10, 2), 0.9, dtype=np.float32))
    plan = [{"sample": str(hit), "at": 0, "pan": 0.5, "fx": "gain=3"}]
    samples.layer(tmp_path / "ok.wav", plan, seconds=1, master="limit=-3")
    settings = manifest(tmp_path, "layer-ok")["settings"]
    assert settings["pedalboard"] is None
    assert 20 * np.log10(np.abs(samples.decode(tmp_path / "ok.wav")).max()) <= -2.99
    with pytest.raises(RuntimeError, match=r"skitz-music\[fx\]"):
        samples.layer(tmp_path / "no.wav", [{**plan[0], "fx": "hp=100"}], seconds=1)


def test_layer_rejects_unknown_placement_keys(tmp_path):
    hit = tmp_path / "hit.wav"
    samples.write_wav(hit, np.zeros((100, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="unknown keys"):
        samples.layer(tmp_path / "x.wav", [{"sample": str(hit), "volume": 3}], seconds=1)
    with pytest.raises(ValueError, match="pan"):
        samples.layer(tmp_path / "x.wav", [{"sample": str(hit), "pan": -2}], seconds=1)


def read_midi(path):
    midi_file = m21midi.MidiFile()
    midi_file.open(str(path))
    midi_file.read()
    midi_file.close()
    return midi_file


def note_ons(track) -> list[tuple[int, int, int]]:
    """(absolute tick, pitch, velocity) for each note-on."""
    ticks, found = 0, []
    for event in track.events:
        if event.isDeltaTime():
            ticks += event.time
        elif event.type == m21midi.ChannelVoiceMessages.NOTE_ON and event.velocity:
            found.append((ticks, event.pitch, event.velocity))
    return found


@needs_fx
def test_export_writes_aligned_stems_samples_and_midi(tmp_path):
    kick = tmp_path / "kick.wav"
    loop = tmp_path / "loop.wav"
    samples.write_wav(kick, clicks(120, 0.25))
    samples.write_wav(loop, sine(330, 2, level=0.3))
    out = tmp_path / "export"
    plan = [
        {"sample": str(kick), "at": 0, "unit": "beat", "repeat": 8, "every": 1, "gain_db": -6},
        {"sample": str(loop), "at": 1, "note": "A2", "fx": {"lowpass": 2000}},
    ]
    result = samples.export_plan(out, plan, bpm=120, bars=4, base=loop, base_gain_db=-12)
    roles = [entry["role"] for entry in result["outputs"]]
    assert roles == ["mix", "stem", "stem", "stem", "sample", "sample", "midi"]
    stems = sorted((out / "stems").glob("*.wav"))
    assert [s.name for s in stems] == ["01-base.wav", "02-kick.wav", "03-loop.wav"]
    assert stems[0].read_bytes()[20:22] == b"\x03\x00"  # IEEE float WAV
    decoded = [samples.decode(stem) for stem in stems]
    assert all(len(d) == 8 * RATE for d in decoded)
    # No master chain and no clipping: the stems sum exactly to the mix.
    mix = samples.decode(out / "mix.wav")
    assert np.abs(sum(decoded) - mix).max() < 2e-4
    assert (out / "samples/kick.wav").is_file() and (out / "samples/loop.wav").is_file()

    midi_file = read_midi(out / "placements.mid")
    assert midi_file.format == 1 and midi_file.ticksPerQuarterNote == 480
    assert len(midi_file.tracks) == 3  # tempo + one per sample track
    tempo = next(e for e in midi_file.tracks[0].events if e.type == m21midi.MetaEvents.SET_TEMPO)
    assert int.from_bytes(tempo.data, "big") == 500_000  # 120 BPM
    kicks = note_ons(midi_file.tracks[1])
    assert [tick for tick, _, _ in kicks] == [480 * n for n in range(8)]
    assert {(pitch, velocity) for _, pitch, velocity in kicks} == {(60, 50)}
    assert note_ons(midi_file.tracks[2]) == [(1920, 57, 100)]  # bar 1 = beat 4; A2 = 57
    settings = manifest(out, "export")["settings"]
    assert settings["midi_bpm"] == 120 and settings["tracks"]["kick"] == [1]


def test_cli_analyze_fit_fx_layer_and_export(tmp_path, capsys):
    source = song(tmp_path, [C, Am, F, G])
    assert samples_main(["analyze", str(source), "--bpm", "120"]) == 0
    assert json.loads(capsys.readouterr().out)["key"]["key"] == "C major"
    if importlib.util.find_spec("pedalboard") is None:
        return
    assert samples_main(["fit", str(source), "-o", str(tmp_path / "fit"), "--semitones", "-2"]) == 0
    fitted = json.loads(capsys.readouterr().out)["outputs"][0]["path"]
    wet = tmp_path / "wet.wav"
    code = samples_main(
        ["fx", fitted, str(wet), "--chain", "hp=80,reverb=0.2,limit", "--tail", "1"]
    )
    assert code == 0, capsys.readouterr().out
    capsys.readouterr()
    assert len(samples.decode(wet)) == 17 * RATE
    beat = tmp_path / "beat.wav"
    args = ["--bpm", "120", "--bars", "2", "--place", f"{wet}:0", "--fx", "1:lp=5000,pan=0.2"]
    assert samples_main(["layer", str(beat), *args, "--master", "limit=-2"]) == 0
    capsys.readouterr()
    assert manifest(tmp_path, "layer-beat")["settings"]["placements"][0]["fx"] == {
        "lowpass": {"hz": 5000}, "pan": {"position": 0.2},
    }  # fmt: skip
    assert samples_main(["export", str(tmp_path / "daw"), *args]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 4  # mix, stem, sample, midi
    assert samples_main(["layer", str(beat), *args[:-2], "--fx", "3:pan=0"]) == 1
    assert "only 1 placements" in capsys.readouterr().out


def test_service_confines_new_tools(tmp_path):
    source = song(tmp_path, [C, Am, F, G], drums=False)
    service = samples.SamplesService(tmp_path)
    for call in (
        lambda: service.samples_analyze("../song.wav"),
        lambda: service.samples_fit("song.wav", "../out", semitones=1),
        lambda: service.samples_fx("song.wav", "../wet.wav", "gain=-1"),
        lambda: service.samples_export("../daw", [{"sample": "song.wav"}], seconds=1),
        lambda: service.samples_export("daw", [{"sample": "/etc/hosts"}], seconds=1),
    ):
        with pytest.raises(ValueError, match="escapes"):
            call()
    assert service.samples_analyze(source.name, bpm=120)["key"]["key"] == "C major"
    result = service.samples_fx(source.name, "wet.wav", {"gain_db": -6, "limit": True})
    assert result["outputs"][0]["peak_dbfs"] == pytest.approx(-6 - 20 * np.log10(1 / 0.5), abs=0.1)
