import json
import os
import shutil
import sys
import textwrap

import numpy as np
import pytest
from skitz_music import samples, separate
from skitz_music.samples_cli import main as samples_main

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

FAKE = textwrap.dedent(
    """
    # Stand-in for audio-separator: writes one WAV per stem named the way it does.
    import sys, wave, pathlib
    args = sys.argv[1:]
    source = pathlib.Path(args[0])
    model = args[args.index("--model_filename") + 1]
    out = pathlib.Path(args[args.index("--output_dir") + 1])
    stems = {"MDX23C-DrumSep-aufr33-jarredou.ckpt": ["kick", "snare", "toms", "hh", "ride", "crash"]}
    names = stems.get(model, ["vocals", "drums", "bass", "guitar", "piano", "other"])
    for i, name in enumerate(names):
        with wave.open(str(out / f"{source.stem}_({name})_{model.split('.')[0]}.wav"), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
            level = 0 if name == "piano" else 1000 * (i + 1)
            w.writeframes((level).to_bytes(2, "little", signed=True) * 2 * 44100)
    print("setting Torch device to MPS", file=sys.stderr)
    """
)


@pytest.fixture
def fake_separator(tmp_path, monkeypatch):
    script = tmp_path / "fake_separator.py"
    script.write_text(FAKE)
    monkeypatch.setenv("SKITZ_SEPARATOR", f"{sys.executable} {script}")
    monkeypatch.setenv("SKITZ_SEPARATION_MODELS", str(tmp_path / "models"))
    source = tmp_path / "songs/clip.wav"
    samples.write_wav(source, np.full((44100, 2), 0.2, dtype=np.float32))
    (source.parent / "manifest.json").write_text(
        json.dumps(
            {
                "source": "suno",
                "request": {"skitz_bpm": 96},
                "files": [{"clip_id": "clip-9", "path": str(source)}],
            }
        )
    )
    return source


def test_stems_are_renamed_measured_and_recorded(fake_separator, tmp_path):
    out = tmp_path / "stems"
    result = separate.separate(fake_separator, out)
    assert set(result["stems"]) == {"vocals", "drums", "bass", "guitar", "piano", "other"}
    assert result["device"] == "MPS"
    assert result["stems"]["piano"]["silent"] is True
    assert result["stems"]["drums"]["silent"] is False
    assert not list(out.glob(".separating-*"))
    manifest = json.loads((out / "separate-manifest.json").read_text())
    assert manifest["model"] == "BS-Roformer-SW.ckpt"
    assert manifest["source"]["suno"]["clip_id"] == "clip-9"
    assert manifest["bpm"] == 96
    # Stems inherit the Suno tempo, so loops land on the bar grid without --bpm.
    assert samples.suno_bpm(out / "drums.wav") == 96


def test_drumkit_splits_the_drum_stem(fake_separator, tmp_path):
    result = separate.separate(fake_separator, tmp_path / "stems", drumkit=True)
    kit = result["drumkit"]["stems"]
    assert set(kit) == {"kick", "snare", "toms", "hh", "ride", "crash"}
    assert (tmp_path / "stems/drums-kit/kick.wav").is_file()


def test_separator_failure_is_reported(tmp_path, monkeypatch, fake_separator):
    monkeypatch.setenv("SKITZ_SEPARATOR", f"{sys.executable} -c 'import sys; sys.exit(3)'")
    with pytest.raises(RuntimeError, match="audio-separator failed"):
        separate.separate(fake_separator, tmp_path / "stems")


def test_cli_and_service(fake_separator, tmp_path, capsys):
    assert samples_main(["stems", str(fake_separator), "-o", str(tmp_path / "cli")]) == 0
    assert json.loads(capsys.readouterr().out)["model"] == "BS-Roformer-SW.ckpt"
    service = samples.SamplesService(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        service.samples_stems("songs/clip.wav", "../outside")
    with pytest.raises(ValueError, match="Unknown"):
        service.samples_stems("songs/clip.wav", "stems", model="--evil")
    assert service.samples_stems("songs/clip.wav", "stems", model="vocals")["stems"]


@pytest.mark.skipif(
    not os.environ.get("SKITZ_REAL_SEPARATION"),
    reason="downloads ~700 MB; set SKITZ_REAL_SEPARATION=1 to run the real model",
)
def test_real_model_on_the_gpu(tmp_path):
    t = np.arange(44100 * 10) / 44100
    tone = (0.3 * np.sin(2 * np.pi * 55 * t)).astype(np.float32)
    source = tmp_path / "bass.wav"
    samples.write_wav(source, np.stack([tone, tone], axis=1))
    result = separate.separate(source, tmp_path / "stems")
    assert set(result["stems"]) >= {"vocals", "drums", "bass", "other"}
