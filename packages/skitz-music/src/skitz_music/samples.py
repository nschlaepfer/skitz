"""Turn audio (usually Suno clips) into loops and one-shots, and layer them into new audio.

Everything is decoded through ffmpeg to 44.1 kHz stereo float arrays, so mp3, wav and
Skitz score renders mix on the same grid. Each operation writes 16-bit WAV files and a
manifest with source hashes, cut points and settings. Tempo detection is an estimate;
pass the BPM you asked Suno for when you know it.
"""

import hashlib
import json
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100
CHANNELS = 2


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("Sample tools need ffmpeg: brew install ffmpeg")
    return executable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode(path: str | Path) -> np.ndarray:
    """Return float32 audio shaped (frames, 2) at 44.1 kHz."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"No audio file at {path}")
    result = subprocess.run(
        [
            _ffmpeg(),
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-",
        ],
        capture_output=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {path}: {result.stderr.decode()[-500:]}")
    pcm = np.frombuffer(result.stdout, dtype="<i2").reshape(-1, CHANNELS)
    return pcm.astype(np.float32) / 32768.0


def write_wav(path: Path, audio: np.ndarray) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).round().astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return {
        "path": str(path),
        "seconds": round(len(audio) / SAMPLE_RATE, 4),
        "peak_dbfs": _dbfs(float(np.abs(audio).max()) if len(audio) else 0.0),
        "sha256": sha256(path),
    }


def _dbfs(peak: float) -> float | None:
    return round(20 * np.log10(peak), 2) if peak > 0 else None


def _fade(audio: np.ndarray, fade_ms: float) -> np.ndarray:
    frames = min(int(SAMPLE_RATE * fade_ms / 1000), len(audio) // 2)
    if frames > 0:
        ramp = np.linspace(0.0, 1.0, frames, dtype=np.float32)[:, None]
        audio = audio.copy()
        audio[:frames] *= ramp
        audio[-frames:] *= ramp[::-1]
    return audio


def _normalize(audio: np.ndarray, peak_dbfs: float = -1.0) -> np.ndarray:
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    return audio * (10 ** (peak_dbfs / 20) / peak) if peak > 0 else audio


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-") or "sample"


def bar_seconds(bpm: float, beats_per_bar: int = 4) -> float:
    if bpm <= 0:
        raise ValueError("BPM must be positive")
    return beats_per_bar * 60.0 / bpm


def _source_info(path: Path) -> dict:
    info: dict = {"path": str(path), "sha256": sha256(path)}
    manifest = path.parent / "manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text())
        except ValueError:
            data = {}
        if data.get("source") == "suno":
            match = next(
                (f for f in data.get("files", []) if Path(f["path"]).name == path.name), None
            )
            info["suno"] = {
                "clip_id": match and match["clip_id"],
                "request": data.get("request"),
            }
    return info


def suno_bpm(path: Path) -> float | None:
    """BPM recorded by `skitz suno generate --bpm` in the clip's manifest, if any."""
    request = (_source_info(path).get("suno") or {}).get("request") or {}
    return request.get("skitz_bpm")


def _onset_envelope(audio: np.ndarray, hop: int = 512, size: int = 2048) -> np.ndarray:
    mono = audio.mean(axis=1)
    if len(mono) < size:
        return np.zeros(1, dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(size), axis=1))
    flux = np.maximum(np.diff(np.log1p(spectrum), axis=0), 0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    return (flux / flux.max()).astype(np.float32) if flux.max() > 0 else flux


def estimate_bpm(audio: np.ndarray, low: float = 70, high: float = 180) -> float | None:
    """Rough tempo estimate from onset autocorrelation; may be off by 2x."""
    hop = 512
    envelope = _onset_envelope(audio, hop)
    envelope = envelope - envelope.mean()
    if len(envelope) < 64 or not envelope.any():
        return None
    correlation = np.correlate(envelope, envelope, mode="full")[len(envelope) - 1 :]
    rate = SAMPLE_RATE / hop
    lags = np.arange(int(rate * 60 / high), min(int(rate * 60 / low) + 1, len(correlation)))
    if not len(lags):
        return None
    best = lags[np.argmax(correlation[lags])]
    return round(60 * rate / best, 1)


def info(source: str | Path) -> dict:
    path = Path(source)
    audio = decode(path)
    return {
        **_source_info(path),
        "seconds": round(len(audio) / SAMPLE_RATE, 3),
        "peak_dbfs": _dbfs(float(np.abs(audio).max()) if len(audio) else 0.0),
        "suno_bpm": suno_bpm(path),
        "estimated_bpm": estimate_bpm(audio),
    }


def _write_manifest(
    directory: Path, operation: str, settings: dict, source: dict | None, outputs: list[dict]
) -> dict:
    manifest = {
        "operation": operation,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "source": source,
        "settings": settings,
        "outputs": outputs,
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{operation}-manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"directory": str(directory), "count": len(outputs), "outputs": outputs}


def slice_sample(
    source: str | Path,
    output_dir: str | Path,
    start: float,
    end: float,
    name: str | None = None,
    fade_ms: float = 5,
    normalize: bool = False,
) -> dict:
    """Cut one region (in seconds) into a WAV."""
    path, out = Path(source), Path(output_dir)
    audio = decode(path)
    if not 0 <= start < end:
        raise ValueError("Need 0 <= start < end")
    region = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
    if not len(region):
        raise ValueError("Region is past the end of the audio")
    region = _fade(region, fade_ms)
    if normalize:
        region = _normalize(region)
    stem = _slug(name or f"{path.stem}-{start:.2f}-{end:.2f}")
    entry = {"start": start, "end": end, **write_wav(out / f"{stem}.wav", region)}
    settings = {"start": start, "end": end, "fade_ms": fade_ms, "normalize": normalize}
    return _write_manifest(out, f"slice-{stem}", settings, _source_info(path), [entry])


def chop_loops(
    source: str | Path,
    output_dir: str | Path,
    bpm: float | None = None,
    bars: int = 1,
    beats_per_bar: int = 4,
    offset: float = 0.0,
    every: float | None = None,
    max_slices: int = 64,
    fade_ms: float = 3,
    normalize: bool = False,
) -> dict:
    """Cut audio into back-to-back loops: `bars` long at `bpm`, or `every` seconds."""
    path, out = Path(source), Path(output_dir)
    audio = decode(path)
    bpm = bpm or suno_bpm(path)
    if every is None:
        if not bpm:
            raise ValueError(
                "Give bpm (or every=seconds). Generate with --bpm so Suno clips carry it."
            )
        every = bar_seconds(bpm, beats_per_bar) * bars
    length = int(every * SAMPLE_RATE)
    if length <= 0:
        raise ValueError("Loop length must be positive")
    outputs = []
    cursor = int(offset * SAMPLE_RATE)
    while cursor + length <= len(audio) and len(outputs) < max_slices:
        loop = _fade(audio[cursor : cursor + length], fade_ms)
        if normalize:
            loop = _normalize(loop)
        index = len(outputs) + 1
        entry = write_wav(out / f"{_slug(path.stem)}-loop{index:02d}.wav", loop)
        outputs.append({"index": index, "start": round(cursor / SAMPLE_RATE, 4), **entry})
        cursor += length
    if not outputs:
        raise ValueError("Audio is shorter than one loop")
    settings = {
        "bpm": bpm,
        "bars": bars,
        "beats_per_bar": beats_per_bar,
        "offset": offset,
        "seconds_per_loop": round(every, 4),
        "fade_ms": fade_ms,
        "normalize": normalize,
    }
    return _write_manifest(out, "loops", settings, _source_info(path), outputs)


def chop_hits(
    source: str | Path,
    output_dir: str | Path,
    sensitivity: float = 0.3,
    max_hits: int = 32,
    max_length: float = 1.0,
    min_gap: float = 0.08,
    normalize: bool = True,
) -> dict:
    """Find transients and cut each into a one-shot (drum hits, stabs, plucks)."""
    path, out = Path(source), Path(output_dir)
    audio = decode(path)
    hop = 512
    envelope = _onset_envelope(audio, hop)
    window = 16
    padded = np.pad(envelope, window, mode="edge")
    local = np.array([np.median(padded[i : i + 2 * window + 1]) for i in range(len(envelope))])
    threshold = local + sensitivity * (1 - local)
    candidates = [
        i
        for i in range(1, len(envelope) - 1)
        if envelope[i] > threshold[i]
        and envelope[i] >= envelope[i - 1]
        and envelope[i] >= envelope[i + 1]
    ]
    onsets: list[int] = []
    for frame in candidates:
        position = frame * hop
        if not onsets or position - onsets[-1] >= min_gap * SAMPLE_RATE:
            onsets.append(position)
    # Keep the strongest hits, then restore time order.
    strength = {o: envelope[o // hop] for o in onsets}
    onsets = sorted(sorted(onsets, key=strength.get, reverse=True)[:max_hits])
    outputs = []
    pre = int(0.005 * SAMPLE_RATE)
    for index, onset in enumerate(onsets, 1):
        following = onsets[index] if index < len(onsets) else len(audio)
        end = min(following, onset + int(max_length * SAMPLE_RATE), len(audio))
        hit = audio[max(onset - pre, 0) : end].copy()
        tail = min(int(0.03 * SAMPLE_RATE), len(hit) // 2)
        if tail:
            hit[-tail:] *= np.linspace(1.0, 0.0, tail, dtype=np.float32)[:, None]
        if normalize:
            hit = _normalize(hit)
        entry = write_wav(out / f"{_slug(path.stem)}-hit{index:02d}.wav", hit)
        outputs.append({"index": index, "start": round(onset / SAMPLE_RATE, 4), **entry})
    settings = {
        "sensitivity": sensitivity,
        "max_hits": max_hits,
        "max_length": max_length,
        "min_gap": min_gap,
        "normalize": normalize,
    }
    return _write_manifest(out, "hits", settings, _source_info(path), outputs)


def layer(
    output: str | Path,
    placements: list[dict],
    bpm: float | None = None,
    beats_per_bar: int = 4,
    bars: float | None = None,
    seconds: float | None = None,
    base: str | Path | None = None,
    base_gain_db: float = 0.0,
) -> dict:
    """Mix samples onto a timeline, optionally over a base track such as a score render.

    Each placement: {"sample": path, "at": 0, "unit": "bar"|"beat"|"second",
    "gain_db": 0, "repeat": 1, "every": <same unit>}. Bars and beats are 0-based and
    need bpm. Peaks above -1 dBFS are scaled down rather than clipped.
    """
    target = Path(output)

    def to_seconds(value: float, unit: str) -> float:
        if unit == "second":
            return float(value)
        if not bpm:
            raise ValueError(f"Placements in {unit}s need bpm")
        beat = 60.0 / bpm
        return float(value) * (beat * beats_per_bar if unit == "bar" else beat)

    decoded: dict[str, np.ndarray] = {}
    events = []
    for placement in placements:
        sample = str(placement["sample"])
        if sample not in decoded:
            decoded[sample] = decode(sample)
        unit = placement.get("unit", "bar" if bpm else "second")
        if unit not in {"bar", "beat", "second"}:
            raise ValueError(f"Unknown unit {unit}")
        start = to_seconds(placement.get("at", 0), unit)
        step = to_seconds(placement.get("every", 0), unit)
        repeat = int(placement.get("repeat", 1))
        if repeat > 1 and step <= 0:
            raise ValueError("A repeated placement needs a positive 'every'")
        gain = 10 ** (float(placement.get("gain_db", 0)) / 20)
        for n in range(repeat):
            events.append((sample, start + n * step, gain))

    base_audio = decode(base) if base else None
    if seconds is None and bars is not None:
        seconds = to_seconds(bars, "bar")
    if seconds is None:
        ends = [at + len(decoded[s]) / SAMPLE_RATE for s, at, _ in events]
        if base_audio is not None:
            ends.append(len(base_audio) / SAMPLE_RATE)
        seconds = max(ends, default=0.0)
    if seconds <= 0:
        raise ValueError("Nothing to mix")
    mix = np.zeros((int(seconds * SAMPLE_RATE), CHANNELS), dtype=np.float32)
    if base_audio is not None:
        portion = base_audio[: len(mix)]
        mix[: len(portion)] += portion * 10 ** (base_gain_db / 20)
    for sample, at, gain in events:
        begin = int(at * SAMPLE_RATE)
        if begin >= len(mix):
            continue
        clip = decoded[sample][: len(mix) - begin]
        mix[begin : begin + len(clip)] += clip * gain

    peak = float(np.abs(mix).max())
    limited = peak > 10 ** (-1 / 20)
    if limited:
        mix = _normalize(mix)
    entry = write_wav(target, mix)
    sources = {s: sha256(Path(s)) for s in decoded}
    if base:
        sources[str(base)] = sha256(Path(base))
    settings = {
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "seconds": round(seconds, 4),
        "base": str(base) if base else None,
        "base_gain_db": base_gain_db,
        "placements": placements,
        "events": len(events),
        "scaled_to_avoid_clipping": limited,
        "source_sha256": sources,
    }
    return _write_manifest(target.parent, f"layer-{_slug(target.stem)}", settings, None, [entry])


class SamplesService:
    """Workspace-confined sample operations for the MCP server."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def path(self, relative: str) -> Path:
        result = (self.workspace / relative).resolve()
        if not result.is_relative_to(self.workspace):
            raise ValueError("Path escapes the music workspace")
        return result

    def samples_info(self, source: str) -> dict:
        return info(self.path(source))

    def samples_loops(
        self,
        source: str,
        output_dir: str,
        bpm: float | None = None,
        bars: int = 1,
        beats_per_bar: int = 4,
        offset: float = 0.0,
        every: float | None = None,
        normalize: bool = False,
    ) -> dict:
        return chop_loops(
            self.path(source),
            self.path(output_dir),
            bpm,
            bars,
            beats_per_bar,
            offset,
            every,
            normalize=normalize,
        )

    def samples_hits(
        self,
        source: str,
        output_dir: str,
        sensitivity: float = 0.3,
        max_hits: int = 32,
        max_length: float = 1.0,
    ) -> dict:
        return chop_hits(
            self.path(source), self.path(output_dir), sensitivity, max_hits, max_length
        )

    def samples_slice(
        self, source: str, output_dir: str, start: float, end: float, name: str | None = None
    ) -> dict:
        return slice_sample(self.path(source), self.path(output_dir), start, end, name)

    def samples_layer(
        self,
        output: str,
        placements: list[dict],
        bpm: float | None = None,
        beats_per_bar: int = 4,
        bars: float | None = None,
        seconds: float | None = None,
        base: str | None = None,
        base_gain_db: float = 0.0,
    ) -> dict:
        confined = [{**p, "sample": str(self.path(str(p["sample"])))} for p in placements]
        return layer(
            self.path(output),
            confined,
            bpm,
            beats_per_bar,
            bars,
            seconds,
            self.path(base) if base else None,
            base_gain_db,
        )
