import json
import shutil
import subprocess
import wave

import numpy as np
import pytest
from skitz_music import samples
from skitz_music.samples_cli import main as samples_main
from skitz_music.samples_cli import parse_place

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

RATE = samples.SAMPLE_RATE
BPM = 120
BEAT = 60 / BPM


def click_track(seconds: float = 16.0) -> np.ndarray:
    """Decaying 80 Hz thump on every beat: an easy, known-tempo drum loop."""
    audio = np.zeros((int(seconds * RATE), 2), dtype=np.float32)
    t = np.arange(int(0.15 * RATE)) / RATE
    hit = (np.sin(2 * np.pi * 80 * t) * np.exp(-t * 30) * 0.8).astype(np.float32)
    for beat in range(int(seconds / BEAT)):
        start = int(beat * BEAT * RATE)
        audio[start : start + len(hit)] += hit[: len(audio) - start, None]
    return audio


@pytest.fixture
def suno_clip(tmp_path):
    """A click track saved the way `skitz suno generate --bpm 120 --out` saves a clip."""
    folder = tmp_path / "songs/drums"
    wav = folder / "source.wav"
    samples.write_wav(wav, click_track())
    mp3 = folder / "Drums-clip1234.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-b:a", "192k", str(mp3)], check=True)
    wav.unlink()
    manifest = {
        "source": "suno",
        "request": {"tags": "drums, 120 bpm", "skitz_bpm": BPM},
        "files": [{"clip_id": "clip-1234", "path": str(mp3), "sha256": "x"}],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return mp3


def seconds_of(path) -> float:
    with wave.open(str(path)) as handle:
        return handle.getnframes() / handle.getframerate()


def test_info_reads_recorded_and_estimated_bpm(suno_clip):
    result = samples.info(suno_clip)
    assert result["suno_bpm"] == BPM
    assert result["suno"]["clip_id"] == "clip-1234"
    assert abs(result["estimated_bpm"] - BPM) < 3
    assert abs(result["seconds"] - 16) < 0.1


def test_loops_use_the_bpm_recorded_by_suno(suno_clip, tmp_path):
    out = tmp_path / "samples/loops"
    result = samples.chop_loops(suno_clip, out, bars=2)
    assert result["count"] == 4  # 16 s at 120 BPM in 4/4 = 8 bars = 4 two-bar loops
    for index, entry in enumerate(result["outputs"]):
        assert abs(seconds_of(entry["path"]) - 4.0) < 0.001
        assert entry["start"] == pytest.approx(index * 4.0)
    manifest = json.loads((out / "loops-manifest.json").read_text())
    assert manifest["settings"]["bpm"] == BPM
    assert manifest["source"]["suno"]["clip_id"] == "clip-1234"


def test_loops_need_a_tempo_or_length(tmp_path):
    plain = tmp_path / "plain.wav"
    samples.write_wav(plain, click_track(4))
    with pytest.raises(ValueError, match="bpm"):
        samples.chop_loops(plain, tmp_path / "out")
    assert samples.chop_loops(plain, tmp_path / "out", every=1.0)["count"] == 4


def test_hits_land_on_the_beats(suno_clip, tmp_path):
    result = samples.chop_hits(suno_clip, tmp_path / "hits", max_hits=40)
    starts = [entry["start"] for entry in result["outputs"]]
    assert 28 <= len(starts) <= 32
    # mp3 encoder delay and frame hop allow a few tens of milliseconds.
    assert all(abs(s - round(s / BEAT) * BEAT) < 0.05 for s in starts)
    assert all(seconds_of(entry["path"]) <= 1.0 + 0.01 for entry in result["outputs"])


def test_slice_cuts_the_requested_region(suno_clip, tmp_path):
    result = samples.slice_sample(suno_clip, tmp_path / "fx", 2.0, 3.5, name="cut")
    assert abs(seconds_of(tmp_path / "fx/cut.wav") - 1.5) < 0.001
    assert result["outputs"][0]["start"] == 2.0


def test_layer_places_repeats_over_a_base_and_avoids_clipping(tmp_path):
    hit = tmp_path / "hit.wav"
    base = tmp_path / "score.wav"
    samples.write_wav(hit, np.full((RATE // 10, 2), 0.9, dtype=np.float32))
    samples.write_wav(base, np.full((RATE * 3, 2), 0.5, dtype=np.float32))
    out = tmp_path / "out/mix.wav"
    samples.layer(
        out,
        [{"sample": str(hit), "at": 0, "unit": "beat", "repeat": 4, "every": 1}],
        bpm=BPM,
        bars=1,
        base=base,
    )
    assert abs(seconds_of(out) - 2.0) < 0.001  # one bar at 120 BPM
    mixed = samples.decode(out)
    assert abs(mixed).max() <= 10 ** (-1 / 20) + 0.001
    onsets = [int(n * BEAT * RATE) + 10 for n in range(4)]
    between = int(0.3 * RATE)
    assert all(mixed[o, 0] > mixed[between, 0] for o in onsets)
    manifest = json.loads((out.parent / "layer-mix-manifest.json").read_text())
    assert manifest["settings"]["events"] == 4
    assert manifest["settings"]["scaled_to_avoid_clipping"] is True


def test_layer_rejects_bars_without_bpm(tmp_path):
    hit = tmp_path / "hit.wav"
    samples.write_wav(hit, np.zeros((100, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="bpm"):
        samples.layer(tmp_path / "x.wav", [{"sample": str(hit), "at": 1, "unit": "bar"}])


def test_place_syntax():
    assert parse_place("loop.wav:0:x4/2") == {
        "sample": "loop.wav",
        "at": 0.0,
        "unit": "bar",
        "repeat": 4,
        "every": 2.0,
    }
    assert parse_place("kick.wav:3q:x8/4:-4dB") == {
        "sample": "kick.wav",
        "at": 3.0,
        "unit": "beat",
        "repeat": 8,
        "every": 4.0,
        "gain_db": -4.0,
    }
    assert parse_place("fx.wav:1.5s")["unit"] == "second"


def test_cli_layer_end_to_end(suno_clip, tmp_path, capsys):
    loops = tmp_path / "loops"
    assert samples_main(["loops", str(suno_clip), "-o", str(loops)]) == 0
    first = json.loads(capsys.readouterr().out)["outputs"][0]["path"]
    out = tmp_path / "beat.wav"
    code = samples_main(
        ["layer", str(out), "--bpm", "120", "--bars", "4", "--place", f"{first}:0:x4/1"]
    )
    assert code == 0, capsys.readouterr().out
    assert abs(seconds_of(out) - 8.0) < 0.001


def test_service_confines_paths(tmp_path, suno_clip):
    service = samples.SamplesService(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        service.samples_loops("songs/drums/Drums-clip1234.mp3", "../outside", bpm=BPM)
    with pytest.raises(ValueError, match="escapes"):
        service.samples_layer("out.wav", [{"sample": "/etc/hosts", "at": 0, "unit": "second"}])
    result = service.samples_loops("songs/drums/Drums-clip1234.mp3", "samples/loops", bars=4)
    assert result["count"] == 2
