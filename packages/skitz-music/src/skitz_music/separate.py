"""Local stem separation with RoFormer/MDX23C models on the Apple GPU.

Runs python-audio-separator in its own uv tool environment, so PyTorch never enters
the Skitz venv. On Apple Silicon it uses MPS for PyTorch models and CoreML for ONNX.
Model weights are cached under ~/.skitz/models/separation (about 700 MB for the
default). Weight licenses vary: the default BS-RoFormer SW checkpoint has no stated
license, so treat its output as personal-use. `htdemucs_ft` is MIT-licensed.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from .samples import SAMPLE_RATE, _dbfs, _source_info, decode, sha256, suno_bpm

SEPARATOR_VERSION = "0.47.0"

# Measured on an M3 Max: 30 s of audio takes about 8 s per model.
PRESETS = {
    "stems": {
        "model": "BS-Roformer-SW.ckpt",
        "stems": ["vocals", "drums", "bass", "guitar", "piano", "other"],
        "about": "BS-RoFormer SW: top single model for drums and bass on MVSEP (6 stems)",
    },
    "4stem": {
        "model": "htdemucs_ft.yaml",
        "stems": ["vocals", "drums", "bass", "other"],
        "about": "HTDemucs fine-tuned (MIT): 4 stems, older and lower quality than SW",
    },
    "vocals": {
        "model": "vocals_mel_band_roformer.ckpt",
        "stems": ["vocals", "other"],
        "about": "Mel-Band RoFormer by Kimberley Jensen: best vocal SDR in the catalog",
    },
    "drumkit": {
        "model": "MDX23C-DrumSep-aufr33-jarredou.ckpt",
        "stems": ["kick", "snare", "toms", "hh", "ride", "crash"],
        "about": "MDX23C DrumSep: splits a drum stem into kit pieces",
    },
}
DEFAULT_PRESET = "stems"
STEM_NAME = re.compile(r"_\(([^()]+)\)_[^()]*$")


def model_dir() -> Path:
    default = Path.home() / ".skitz/models/separation"
    return Path(os.environ.get("SKITZ_SEPARATION_MODELS", str(default))).expanduser()


def separator_command() -> list[str]:
    override = os.environ.get("SKITZ_SEPARATOR")
    if override:
        return shlex.split(override)
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Stem separation needs uv to run audio-separator")
    return [
        uv, "tool", "run", "--quiet", "--python", "3.12",
        "--from", f"audio-separator[cpu]=={SEPARATOR_VERSION}",
        "--with", "audioread",  # audio-separator 0.47.0 imports it without declaring it
        "audio-separator",
    ]  # fmt: skip


def _stats(path: Path) -> dict:
    audio = decode(path)
    rms = float(np.sqrt((audio**2).mean())) if len(audio) else 0.0
    return {
        "path": str(path),
        "seconds": round(len(audio) / SAMPLE_RATE, 4),
        "rms_dbfs": _dbfs(rms),
        "peak_dbfs": _dbfs(float(np.abs(audio).max()) if len(audio) else 0.0),
        "silent": rms < 10 ** (-70 / 20),
        "sha256": sha256(path),
    }


def separate(
    source: str | Path,
    output_dir: str | Path,
    model: str = DEFAULT_PRESET,
    drumkit: bool = False,
    timeout: float = 1800,
) -> dict:
    """Split audio into stems named `<stem>.wav`, with a manifest.

    `model` is a preset (stems, 4stem, vocals, drumkit) or an audio-separator model
    filename. With `drumkit`, the drums stem is split again into `drums-kit/`.
    """
    path, out = Path(source).resolve(), Path(output_dir)
    if not path.is_file():
        raise ValueError(f"No audio file at {path}")
    preset = PRESETS.get(model)
    filename = preset["model"] if preset else model
    out.mkdir(parents=True, exist_ok=True)
    model_dir().mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(dir=out, prefix=".separating-") as work:
        command = [
            *separator_command(), str(path),
            "--model_filename", filename,
            "--model_file_dir", str(model_dir()),
            "--output_dir", work,
            "--output_format", "WAV",
        ]  # fmt: skip
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Separation timed out after {timeout:.0f}s") from error
        if result.returncode != 0:
            raise RuntimeError(
                f"audio-separator failed: {(result.stderr or result.stdout)[-1500:]}"
            )
        produced = sorted(Path(work).glob("*.wav"))
        if not produced:
            raise RuntimeError(f"audio-separator wrote no stems: {result.stderr[-1500:]}")
        stems = {}
        for file in produced:
            match = STEM_NAME.search(file.stem)
            name = re.sub(r"[^A-Za-z0-9_-]+", "-", match[1] if match else file.stem).lower()
            target = out / f"{name}.wav"
            shutil.move(str(file), target)
            stems[name] = _stats(target)
    seconds = round(time.monotonic() - started, 2)
    device = next(
        (
            line.split("setting Torch device to ")[-1].strip()
            for line in result.stderr.splitlines()
            if "setting Torch device to" in line
        ),
        None,
    )
    report = {
        "operation": "separate",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": _source_info(path),
        "bpm": suno_bpm(path),
        "model": filename,
        "preset": model if preset else None,
        "separator": f"audio-separator {SEPARATOR_VERSION}",
        "device": device,
        "seconds_taken": seconds,
        "stems": stems,
    }
    if drumkit:
        if "drums" not in stems:
            raise ValueError(f"{filename} produced no drums stem to split")
        report["drumkit"] = separate(
            out / "drums.wav", out / "drums-kit", "drumkit", False, timeout
        )
    (out / "separate-manifest.json").write_text(json.dumps(report, indent=2))
    return {
        "directory": str(out),
        "model": filename,
        "device": device,
        "seconds_taken": seconds,
        "stems": stems,
        **({"drumkit": report["drumkit"]} if drumkit else {}),
    }
