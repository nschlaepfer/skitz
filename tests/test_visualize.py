import json
import shutil

import numpy as np
import pytest
from skitz_music import playback, samples, visualize

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

RATE = samples.SAMPLE_RATE


def tone(tmp_path, freq, seconds=2.0, name="tone.wav"):
    t = np.arange(int(RATE * seconds)) / RATE
    mono = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    path = tmp_path / name
    samples.write_wav(path, np.stack([mono, mono], axis=1))
    return path


def test_a_low_tone_lights_the_low_bands_and_a_high_tone_the_high_ones(tmp_path):
    low = visualize.spectrum_frames(tone(tmp_path, 80, name="low.wav"))
    high = visualize.spectrum_frames(tone(tmp_path, 8000, name="high.wav"))
    assert low["bands"] == 32 and low["fps"] == 20
    assert len(low["frames"]) == pytest.approx(40, abs=2)  # 2 s at 20 fps
    middle = len(low["frames"]) // 2
    assert int(np.argmax(low["frames"][middle])) < 8
    assert int(np.argmax(high["frames"][middle])) > 24
    assert all(0 <= level <= 100 for frame in low["frames"] for level in frame)


def test_bars_render_full_partial_and_empty_cells():
    rows = visualize.render_bars([100, 50, 0], height=2, color=False)
    assert rows == ["█  ", "██ "]
    colored = visualize.render_bars([100], height=1)
    assert colored[0].startswith("\x1b[38;2;") and "█" in colored[0]


def test_frame_lookup_by_time():
    data = {"fps": 10, "frames": [[1], [2], [3]]}
    assert visualize.frame_at(data, 0.15) == [2]
    assert visualize.frame_at(data, 5) is None


def test_background_play_publishes_frames_for_the_agent_screen(tmp_path, monkeypatch):
    monkeypatch.setenv("SKITZ_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(playback, "player_command", lambda path: ["sleep", "30"])
    wav = tone(tmp_path, 440)
    result = playback.play(wav, background=True)
    state = json.loads(playback.state_file().read_text())
    assert state["pid"] == result["pid"] and state["title"] == "tone.wav"
    assert state["fps"] == 20 and len(state["frames"]) > 30
    assert playback.stop()["status"] == "stopped"
    assert not playback.state_file().exists()


def test_animations_off_skips_the_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("SKITZ_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("SKITZ_ANIMATIONS", "off")
    monkeypatch.setattr(playback, "player_command", lambda path: ["sleep", "30"])
    playback.play(tone(tmp_path, 440), background=True)
    assert "frames" not in json.loads(playback.state_file().read_text())
    playback.stop()
