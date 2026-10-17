"""Turn audio (usually Suno clips) into loops and one-shots, fit and mix them into new audio.

Everything is decoded through ffmpeg to 44.1 kHz stereo float arrays, so mp3, wav and
Skitz score renders mix on the same grid. Each operation writes WAV files and a
manifest with source hashes, cut points and settings. Tempo, key and chord detection
are estimates from the signal; pass the BPM and key you asked Suno for when you know
them. Time-stretching, pitch-shifting and effects use Spotify's pedalboard (the `fx`
extra), or Rubber Band through ffmpeg for `fit` when pedalboard is not installed.
"""

import functools
import hashlib
import json
import re
import shutil
import struct
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
            "f32le",
            "-acodec",
            "pcm_f32le",
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
    return np.frombuffer(result.stdout, dtype="<f4").reshape(-1, CHANNELS).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, float32: bool = False) -> dict:
    """Write 16-bit PCM (clipped at 0 dBFS), or unclipped 32-bit float for DAW stems."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if float32:
        data = np.ascontiguousarray(audio, dtype="<f4").tobytes()
        block = CHANNELS * 4
        fmt = struct.pack("<HHIIHHH", 3, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * block, block, 32, 0)
        chunks = [(b"fmt ", fmt), (b"fact", struct.pack("<I", len(audio))), (b"data", data)]
        body = b"WAVE" + b"".join(tag + struct.pack("<I", len(c)) + c for tag, c in chunks)
        path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    else:
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
        **({"format": "float32"} if float32 else {}),
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
    """BPM recorded by `skitz suno generate --bpm`, carried onto stems, or set by `fit`."""
    request = (_source_info(path).get("suno") or {}).get("request") or {}
    if request.get("skitz_bpm"):
        return request["skitz_bpm"]
    for name in (f"fit-{path.stem}-manifest.json", f"fx-{path.stem}-manifest.json"):
        made = path.parent / name
        if made.is_file():
            try:
                return json.loads(made.read_text())["settings"].get("bpm")
            except (ValueError, KeyError):
                return None
    separated = path.parent / "separate-manifest.json"
    if separated.is_file():
        try:
            return json.loads(separated.read_text()).get("bpm")
        except ValueError:
            return None
    return None


def _onset_envelope(audio: np.ndarray, hop: int = 512, size: int = 2048) -> np.ndarray:
    mono = audio.mean(axis=1)
    if len(mono) < size:
        return np.zeros(1, dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(size), axis=1))
    flux = np.maximum(np.diff(np.log1p(spectrum), axis=0), 0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    return (flux / flux.max()).astype(np.float32) if flux.max() > 0 else flux


ESTIMATE_NOTE = (
    "Estimated from the signal, not by listening. Tempo can be off by double or half, "
    "relative major/minor keys are easy to confuse, and chords are triads only."
)
PITCH_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MAJOR_KEY_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MINOR_KEY_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
# Krumhansl-Kessler probe-tone profiles, tonic first.
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
TEMPO_HOP = 512
# The spectral-flux peak trails the start of its 2048-sample frame by about this much.
ONSET_LAG = 1536 / SAMPLE_RATE


def estimate_tempo(audio: np.ndarray, low: float = 70, high: float = 180) -> dict | None:
    """Tempo from onset autocorrelation, with confidence, half/double and first beat.

    An estimate: it can lock onto double or half the felt tempo, and `first_beat` is the
    strongest beat phase, not necessarily the downbeat of bar 1.
    """
    rate = SAMPLE_RATE / TEMPO_HOP
    envelope = _onset_envelope(audio, TEMPO_HOP).astype(np.float64)
    centered = envelope - envelope.mean()
    if len(centered) < 64 or not centered.any():
        return None
    spectrum = np.fft.rfft(centered, 2 * len(centered))
    correlation = np.fft.irfft(np.abs(spectrum) ** 2)[: len(centered)]
    first = max(int(rate * 60 / high), 1)
    last = min(int(rate * 60 / low) + 1, len(correlation) - 1)
    if first >= last:
        return None
    best = first + int(np.argmax(correlation[first:last]))

    def peak_near(center: int) -> float:
        """Sub-frame lag of the local peak near `center`, by parabolic interpolation."""
        window = correlation[max(center - 2, 1) : center + 3]
        top = max(center - 2, 1) + int(np.argmax(window))
        before, peak, after = correlation[top - 1 : top + 2]
        curve = before - 2 * peak + after
        return top + (0.5 * (before - after) / curve if curve < 0 else 0.0)

    # Refining on the 4th (or a lower) multiple of the lag cuts the rounding error 4x.
    multiple = next((k for k in (4, 3, 2) if k * best + 3 < len(correlation)), 1)
    lag = peak_near(multiple * best) / multiple
    bpm = 60 * rate / lag
    # Beat phase: the offset whose beat grid collects the most onset strength.
    beats = np.arange(0, len(envelope) - 1, lag)
    phases = np.arange(int(np.ceil(lag)))
    strength = [envelope[np.minimum((beats + phase).round().astype(int), len(envelope) - 1)].sum()
                for phase in phases]  # fmt: skip
    period = 60 / bpm
    first_beat = (phases[int(np.argmax(strength))] * TEMPO_HOP / SAMPLE_RATE + ONSET_LAG) % period
    if period - first_beat < 0.025:
        first_beat = 0.0
    return {
        "bpm": round(bpm, 1),
        "confidence": round(float(np.clip(correlation[best] / correlation[0], 0, 1)), 3),
        "alternatives": [round(bpm / 2, 1), round(bpm * 2, 1)],
        "first_beat": round(first_beat, 3),
        "estimate": True,
        "method": f"onset autocorrelation, searched between {low:g} and {high:g} BPM",
    }


def estimate_bpm(audio: np.ndarray, low: float = 70, high: float = 180) -> float | None:
    """Rough tempo estimate from onset autocorrelation; may be off by 2x."""
    tempo = estimate_tempo(audio, low, high)
    return tempo and tempo["bpm"]


def chromagram(
    audio: np.ndarray, size: int = 16384, hop: int = 4096, low: float = 127.0, high: float = 4200.0
) -> tuple[np.ndarray, np.ndarray]:
    """Pitch-class energy per frame, shaped (frames, 12) from C, and frame centers in seconds."""
    mono = audio.mean(axis=1)
    if len(mono) < size:
        mono = np.pad(mono, (0, size - len(mono)))
    freqs = np.fft.rfftfreq(size, 1 / SAMPLE_RATE)
    band = np.flatnonzero((freqs >= low) & (freqs <= high))
    midi = 69 + 12 * np.log2(freqs[band] / 440.0)
    nearest = np.round(midi)
    weights = np.zeros((len(band), 12))
    weights[np.arange(len(band)), nearest.astype(int) % 12] = 1 - 2 * np.abs(midi - nearest)
    window = np.hanning(size)
    starts = np.arange(0, len(mono) - size + 1, hop)
    chroma = np.empty((len(starts), 12))
    for i in range(0, len(starts), 64):
        block = np.stack([mono[s : s + size] for s in starts[i : i + 64]]) * window
        chroma[i : i + 64] = (np.abs(np.fft.rfft(block, axis=1)[:, band]) ** 2) @ weights
    return chroma, (starts + size / 2) / SAMPLE_RATE


def key_name(tonic: int, mode: str) -> str:
    names = MAJOR_KEY_NAMES if mode == "major" else MINOR_KEY_NAMES
    return f"{names[tonic % 12]} {mode}"


def camelot(tonic: int, mode: str) -> str:
    """DJ wheel code: C major is 8B, A minor 8A; neighbours on the wheel mix cleanly."""
    major = tonic if mode == "major" else tonic + 3
    return f"{(major * 7 % 12 + 7) % 12 + 1}{'B' if mode == 'major' else 'A'}"


KEY_TEXT = re.compile(r"^([A-G])([#b\u266f\u266d]?)\s*(major|maj|minor|min|m)?$", re.IGNORECASE)
CAMELOT_TEXT = re.compile(r"^(1[0-2]|[1-9])([AB])$", re.IGNORECASE)


def parse_key(text: str) -> tuple[int, str]:
    """`A minor`, `Am`, `F#`, `Bb major`, `ebm` or a Camelot code like `8A` -> (tonic, mode)."""
    value = str(text).strip()
    wheel = CAMELOT_TEXT.match(value)
    if wheel:
        mode = "major" if wheel[2].upper() == "B" else "minor"
        tonic = next(t for t in range(12) if camelot(t, mode) == f"{wheel[1]}{wheel[2].upper()}")
        return tonic, mode
    match = KEY_TEXT.match(value)
    if not match:
        raise ValueError(
            f"Unknown key {text!r}; use e.g. 'A minor', 'Am', 'F#', 'Bb major' or '8A'"
        )
    letter, accidental, quality = match[1].upper(), match[2], (match[3] or "").lower()
    tonic = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter]
    tonic += {"#": 1, "\u266f": 1, "b": -1, "B": -1, "\u266d": -1}.get(accidental, 0)
    return tonic % 12, "minor" if quality in {"m", "min", "minor"} else "major"


def key_shift(source: tuple[int, str], target: tuple[int, str]) -> tuple[int, str]:
    """Semitones (-6..5) that move `source` onto `target`, and how the keys relate.

    Between a major and a minor key, the shift lands on the target's relative key, which
    shares its notes: C major fits A minor with no shift.
    """
    (from_tonic, from_mode), (to_tonic, to_mode) = source, target
    if from_mode == to_mode:
        difference, relation = to_tonic - from_tonic, "same mode"
    else:
        relative = {"major": 0, "minor": 3}
        difference = (to_tonic + relative[to_mode]) - (from_tonic + relative[from_mode])
        relation = "relative"
    return (difference + 6) % 12 - 6, relation


# Major and minor triads that belong to a key, as (semitones above the tonic, quality).
# Minor includes the harmonic-minor V. Diminished triads are not detected, so they are left out.
DIATONIC_TRIADS = {
    "major": {(0, "major"), (2, "minor"), (4, "minor"), (5, "major"), (7, "major"), (9, "minor")},
    "minor": {(0, "minor"), (3, "major"), (5, "minor"), (7, "minor"), (7, "major"), (8, "major"),
              (10, "major")},
}  # fmt: skip
CHORD_WEIGHT = 0.2


def _chord_fit(tonic: int, mode: str, segments: list[dict]) -> float:
    """0-2.5: time in diatonic chords, plus time on the tonic chord, plus starting/ending on it.

    Root harmonics put a major third into most chroma, so the profile alone often ties a
    minor key with its parallel major; the tonic chord's quality breaks the tie.
    """
    chords = [
        (PITCH_NAMES.index(s["root"]), s["quality"], s["end"] - s["start"])
        for s in segments
        if s["root"] is not None
    ]
    total = sum(length for *_, length in chords)
    if not total:
        return 0.0
    diatonic = {((tonic + step) % 12, quality) for step, quality in DIATONIC_TRIADS[mode]}
    home = (tonic, mode)
    inside = sum(length for root, q, length in chords if (root, q) in diatonic)
    on_tonic = sum(length for root, q, length in chords if (root, q) == home)
    ends = ((chords[0][:2] == home) + (chords[-1][:2] == home)) / 2
    return (inside + on_tonic) / total + 0.5 * ends


def estimate_key(audio: np.ndarray, segments: list[dict] | None = None) -> dict | None:
    """Key and mode: average chroma against Krumhansl-Kessler profiles, refined by how well
    estimated chords (from `estimate_chords`) fit each key when they are given."""
    chroma, _ = chromagram(audio)
    energy = chroma.sum(axis=1)
    if not len(energy) or energy.max() <= 0:
        return None
    loud = energy > energy.max() * 1e-4
    profile = (chroma[loud] / energy[loud, None]).mean(axis=0)
    scores = []
    for tonic in range(12):
        for mode, template in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            correlation = float(np.corrcoef(profile, np.roll(template, tonic))[0, 1])
            fit = _chord_fit(tonic, mode, segments) if segments else 0.0
            scores.append((correlation + CHORD_WEIGHT * fit, correlation, fit, tonic, mode))
    scores.sort(reverse=True)
    score, correlation, fit, tonic, mode = scores[0]
    method = "average chroma against Krumhansl-Kessler key profiles"
    return {
        "key": key_name(tonic, mode),
        "tonic": MAJOR_KEY_NAMES[tonic] if mode == "major" else MINOR_KEY_NAMES[tonic],
        "mode": mode,
        "camelot": camelot(tonic, mode),
        "correlation": round(correlation, 3),
        **({"chord_fit": round(fit, 3)} if segments else {}),
        "confidence": round(score - scores[1][0], 3),
        "alternatives": [
            {"key": key_name(t, m), "correlation": round(c, 3)} for _, c, _, t, m in scores[1:4]
        ],
        "estimate": True,
        "method": method + (", weighed with the estimated chords" if segments else ""),
    }


def _chord_templates() -> tuple[list[tuple[str, int, str]], np.ndarray]:
    labels, rows = [], []
    for quality, intervals in (("major", (0, 4, 7)), ("minor", (0, 3, 7))):
        for root in range(12):
            row = np.zeros(12)
            row[[(root + i) % 12 for i in intervals]] = 1
            labels.append((PITCH_NAMES[root] + ("m" if quality == "minor" else ""), root, quality))
            rows.append(row / np.linalg.norm(row))
    return labels, np.array(rows)


def estimate_chords(
    audio: np.ndarray,
    bpm: float,
    beats_per_bar: int = 4,
    offset: float = 0.0,
    window_beats: float | None = None,
) -> list[dict]:
    """One major/minor triad (or N for silence) per window on the beat grid, merged."""
    window = (window_beats or beats_per_bar) * 60.0 / bpm
    bar = beats_per_bar * 60.0 / bpm
    duration = len(audio) / SAMPLE_RATE
    chroma, times = chromagram(audio)
    labels, templates = _chord_templates()
    windows = []
    start = max(offset, 0.0)
    while start < duration - 0.05:
        end = min(start + window, duration)
        mask = (times >= start) & (times < end)
        windows.append((start, end, chroma[mask].sum(axis=0) if mask.any() else np.zeros(12)))
        start += window
    loudest = max((v.sum() for _, _, v in windows), default=0.0)
    segments: list[dict] = []
    for start, end, vector in windows:
        if loudest <= 0 or vector.sum() < loudest * 1e-4:
            label, root, quality, confidence = "N", None, None, 1.0
        else:
            scores = templates @ (vector / np.linalg.norm(vector))
            order = np.argsort(scores)[::-1]
            label, root, quality = labels[order[0]]
            confidence = float(scores[order[0]] - scores[order[1]])
        if segments and segments[-1]["chord"] == label:
            segments[-1]["end"] = round(end, 3)
            segments[-1]["_confidence"].append(confidence)
            continue
        segments.append(
            {
                "chord": label,
                "root": PITCH_NAMES[root] if root is not None else None,
                "quality": quality,
                "start": round(start, 3),
                "end": round(end, 3),
                "bar": round((start - offset) / bar, 3),
                "_confidence": [confidence],
            }
        )
    for segment in segments:
        segment["confidence"] = round(float(np.mean(segment.pop("_confidence"))), 3)
    return segments


def analyze(
    source: str | Path,
    bpm: float | None = None,
    beats_per_bar: int = 4,
    offset: float = 0.0,
    chord_beats: float | None = None,
) -> dict:
    """Estimated tempo, key/mode and chords, each labelled as an estimate.

    Chords sit on a grid of `chord_beats` (default one bar) from `offset`, at `bpm`, the
    recorded Suno BPM or else the estimated tempo.
    """
    path = Path(source)
    audio = decode(path)
    tempo = estimate_tempo(audio)
    recorded = suno_bpm(path)
    grid_bpm, grid_from = bpm, "argument"
    if not grid_bpm and recorded:
        grid_bpm, grid_from = recorded, "recorded"
    if not grid_bpm and tempo:
        grid_bpm, grid_from = tempo["bpm"], "estimate"
    segments = (
        estimate_chords(audio, grid_bpm, beats_per_bar, offset, chord_beats) if grid_bpm else []
    )
    return {
        **_source_info(path),
        "seconds": round(len(audio) / SAMPLE_RATE, 3),
        "estimate": True,
        "note": ESTIMATE_NOTE,
        "tempo": {**(tempo or {"bpm": None, "estimate": True}), "recorded_bpm": recorded},
        "key": estimate_key(audio, segments) or {"key": None, "estimate": True},
        "chords": {
            "estimate": True,
            "method": "chroma per window against major/minor triad templates",
            "grid": {
                "bpm": grid_bpm,
                "bpm_from": grid_from if grid_bpm else None,
                "beats_per_bar": beats_per_bar,
                "offset": offset,
                "window_beats": chord_beats or beats_per_bar,
            },
            "progression": [s["chord"] for s in segments],
            "segments": segments,
        },
    }


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


def _pedalboard():
    try:
        import pedalboard
    except ImportError as error:
        raise RuntimeError(
            "Effects need pedalboard: pip install 'skitz-music[fx]' "
            "(uv sync in the Skitz checkout installs it)"
        ) from error
    return pedalboard


@functools.cache
def _ffmpeg_rubberband() -> str | None:
    """ffmpeg's version line if it was built with librubberband, else None."""
    executable = shutil.which("ffmpeg")
    if not executable:
        return None
    filters = subprocess.run(
        [executable, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30
    ).stdout
    if not re.search(r"\srubberband\s", filters):
        return None
    version = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=30)
    return version.stdout.splitlines()[0] if version.stdout else "ffmpeg"


def _stretch(audio: np.ndarray, tempo_ratio: float, semitones: float, engine: str):
    """Change speed by `tempo_ratio` and pitch by `semitones` independently."""
    if engine not in {"auto", "pedalboard", "rubberband"}:
        raise ValueError("engine must be auto, pedalboard or rubberband")
    if engine != "rubberband":
        try:
            pedalboard = _pedalboard()
        except RuntimeError:
            if engine == "pedalboard":
                raise
        else:
            stretched = pedalboard.time_stretch(
                np.ascontiguousarray(audio.T, dtype=np.float32),
                float(SAMPLE_RATE),
                stretch_factor=tempo_ratio,
                pitch_shift_in_semitones=semitones,
                high_quality=True,
                transient_mode="crisp",
            )
            info = {"name": "pedalboard", "version": pedalboard.__version__}
            return stretched.T, {**info, "library": "Rubber Band (in pedalboard)"}
    version = _ffmpeg_rubberband()
    if not version:
        raise RuntimeError(
            "fit needs pedalboard (pip install 'skitz-music[fx]') or an ffmpeg built with "
            "librubberband (brew install ffmpeg)"
        )
    pitch = 2 ** (semitones / 12)
    raw = ["-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS)]
    result = subprocess.run(
        [
            _ffmpeg(), "-v", "error", *raw, "-i", "pipe:0",
            "-af", f"rubberband=tempo={tempo_ratio:.6f}:pitch={pitch:.6f}:transients=crisp",
            *raw, "pipe:1",
        ],
        input=np.ascontiguousarray(audio, dtype="<f4").tobytes(),
        capture_output=True,
        timeout=600,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg rubberband failed: {result.stderr.decode()[-500:]}")
    stretched = np.frombuffer(result.stdout, dtype="<f4").reshape(-1, CHANNELS)
    return stretched, {"name": "ffmpeg-rubberband", "version": version}


def _key_label(tonic: int, mode: str) -> str:
    names = MAJOR_KEY_NAMES if mode == "major" else MINOR_KEY_NAMES
    return names[tonic] + ("m" if mode == "minor" else "")


def fit_sample(
    source: str | Path,
    output_dir: str | Path,
    bpm: float | None = None,
    key: str | None = None,
    source_bpm: float | None = None,
    source_key: str | None = None,
    semitones: float | None = None,
    engine: str = "auto",
    name: str | None = None,
    normalize: bool = False,
) -> dict:
    """Time-stretch to `bpm` and/or pitch-shift to `key` (or by `semitones`), independently.

    The source tempo comes from `source_bpm`, the recorded Suno/fit BPM, or an estimate;
    the source key from `source_key` or an estimate. The manifest records which, and the
    tempo and pitch ratios used. Output length is exactly input length / tempo ratio.
    """
    path, out = Path(source), Path(output_dir)
    if bpm is None and key is None and semitones is None:
        raise ValueError("Give a target bpm, key or semitones")
    if key is not None and semitones is not None:
        raise ValueError("Give key or semitones, not both")
    audio = decode(path)
    if not len(audio):
        raise ValueError(f"{path} has no audio")
    settings: dict = {"target_bpm": bpm, "target_key": None, "estimated": []}
    tempo_ratio, origin = 1.0, None
    recorded = suno_bpm(path)
    if (bpm is not None and bpm <= 0) or (source_bpm is not None and source_bpm <= 0):
        raise ValueError("BPM must be positive")
    if bpm is not None:
        if source_bpm:
            origin = "argument"
        elif recorded:
            source_bpm, origin = recorded, "recorded"
        else:
            tempo = estimate_tempo(audio)
            if not tempo:
                raise ValueError("Could not estimate the source tempo; pass source_bpm")
            source_bpm, origin = tempo["bpm"], "estimate"
            settings["estimated"].append("source_bpm")
        tempo_ratio = bpm / source_bpm
    elif source_bpm or recorded:
        source_bpm, origin = source_bpm or recorded, "argument" if source_bpm else "recorded"
    if not 0.25 <= tempo_ratio <= 4:
        raise ValueError(f"Tempo ratio {tempo_ratio:.3f} is outside 0.25-4; check the BPMs")
    shift, relation, from_key, key_origin, result_key = 0.0, None, None, None, None
    if semitones is not None:
        shift = float(semitones)
    elif key is not None:
        target = parse_key(key)
        if source_key:
            start, key_origin = parse_key(source_key), "argument"
        else:
            grid = source_bpm or (estimate_tempo(audio) or {}).get("bpm")
            estimate = estimate_key(audio, estimate_chords(audio, grid) if grid else None)
            if not estimate:
                raise ValueError("Could not estimate the source key; pass source_key")
            start, key_origin = parse_key(estimate["key"]), "estimate"
            settings["estimated"].append("source_key")
        shift, relation = key_shift(start, target)
        # A relative fit lands on the target's relative key, e.g. C major fit to D minor is F major.
        from_key, result_key = key_name(*start), key_name(start[0] + shift, start[1])
        settings["target_key"] = key_name(*target)
    if abs(shift) > 24:
        raise ValueError("Pitch shifts are limited to two octaves")
    if tempo_ratio == 1 and shift == 0:
        processed, engine_info = audio, {"name": "none", "reason": "nothing to change"}
    else:
        processed, engine_info = _stretch(audio, tempo_ratio, shift, engine)
    frames = round(len(audio) / tempo_ratio)
    processed = np.ascontiguousarray(processed[:frames], dtype=np.float32)
    if len(processed) < frames:
        processed = np.pad(processed, ((0, frames - len(processed)), (0, 0)))
    if normalize:
        processed = _normalize(processed)
    peak = float(np.abs(processed).max())
    scaled = peak > 1.0
    if scaled:
        processed = _normalize(processed)
    parts = [path.stem]
    if bpm is not None:
        parts.append(f"{bpm:g}bpm")
    if key is not None:
        parts.append(_key_label(*parse_key(key)))
    elif semitones is not None:
        parts.append(f"{'up' if shift > 0 else 'down'}{abs(shift):g}st")
    stem = _slug(name or "-".join(parts))
    entry = write_wav(out / f"{stem}.wav", processed)
    settings.update(
        source_bpm=source_bpm,
        source_bpm_from=origin,
        tempo_ratio=round(tempo_ratio, 6),
        length_ratio=round(1 / tempo_ratio, 6),
        source_key=from_key,
        source_key_from=key_origin,
        key_relation=relation,
        semitones=shift,
        pitch_ratio=round(2 ** (shift / 12), 6),
        bpm=bpm if bpm is not None else source_bpm,
        key=result_key,
        engine=engine_info,
        normalize=normalize,
        scaled_to_avoid_clipping=scaled,
    )
    return _write_manifest(out, f"fit-{stem}", settings, _source_info(path), [entry])


# Effects run in this order wherever they appear: a placement's `fx`, the master and `fx`.
FX_ORDER = [
    "highpass", "lowpass", "low_shelf", "high_shelf", "peak",
    "compress", "delay", "reverb", "gain_db", "pan", "limit",
]  # fmt: skip
FX_ALIASES = {
    **{name: name for name in FX_ORDER},
    "hp": "highpass", "lp": "lowpass",
    "lowshelf": "low_shelf", "ls": "low_shelf",
    "highshelf": "high_shelf", "hs": "high_shelf",
    "eq": "peak", "bell": "peak",
    "comp": "compress", "compressor": "compress",
    "echo": "delay", "verb": "reverb",
    "gain": "gain_db", "limiter": "limit",
}  # fmt: skip
FX_FIELDS = {
    "highpass": {"hz": None, "slope": 12},
    "lowpass": {"hz": None, "slope": 12},
    "low_shelf": {"hz": None, "db": None, "q": 0.707},
    "high_shelf": {"hz": None, "db": None, "q": 0.707},
    "peak": {"hz": None, "db": None, "q": 1.0},
    "compress": {
        "threshold_db": -18.0, "ratio": 4.0, "attack_ms": 5.0, "release_ms": 100.0,
        "makeup_db": 0.0,
    },
    "delay": {"time": None, "feedback": 0.3, "mix": 0.25},
    "reverb": {"wet": 0.2, "room": 0.5, "damping": 0.5, "width": 1.0, "dry": 1.0},
    "gain_db": {"db": None},
    "pan": {"position": None},
    "limit": {"ceiling_db": -1.0, "release_ms": 100.0, "lookahead_ms": 5.0},
}  # fmt: skip
FX_RANGES = {
    "hz": (10, 22000), "slope": (6, 24), "db": (-48, 24), "q": (0.1, 18),
    "threshold_db": (-60, 0), "ratio": (1, 50), "attack_ms": (0.01, 1000),
    "release_ms": (1, 5000), "makeup_db": (-24, 24), "seconds": (0.001, 10),
    "feedback": (0, 0.95), "mix": (0, 1), "wet": (0, 1), "room": (0, 1), "damping": (0, 1),
    "width": (0, 1), "dry": (0, 1), "position": (-1, 1), "ceiling_db": (-60, 0),
    "lookahead_ms": (0.1, 50),
}  # fmt: skip
# Limiting and the clip-safety check share this ceiling; the tolerance absorbs float rounding.
SAFE_PEAK = 10 ** (-1 / 20) * 1.0001


def parse_chain(text: str) -> dict:
    """Parse `hp=120/24,lowshelf=200/-3,comp=-18/4,delay=0.75q/0.3/0.25,reverb=0.2,pan=-0.5`.

    Values after `=` fill the effect's fields in order, separated by `/`: highpass and
    lowpass HZ/SLOPE; shelves and peak HZ/DB/Q; comp THRESHOLD/RATIO/ATTACK/RELEASE/MAKEUP;
    delay TIME/FEEDBACK/MIX (TIME in seconds, or beats with a `q` suffix);
    reverb WET/ROOM/DAMPING/WIDTH; gain DB; pan -1..1; limit CEILING/RELEASE/LOOKAHEAD
    (a bare `limit` caps peaks at -1 dBFS).
    """
    spec: dict = {}
    for part in filter(None, (piece.strip() for piece in str(text).split(","))):
        label, _, value = part.partition("=")
        effect = FX_ALIASES.get(label.strip().lower())
        if not effect:
            raise ValueError(f"Unknown effect {label!r}; use one of {', '.join(FX_ALIASES)}")
        fields = [field.strip() for field in value.split("/")] if value.strip() else []
        names = list(FX_FIELDS[effect])
        if len(fields) > len(names):
            raise ValueError(f"{effect} takes at most {len(names)} values: {'/'.join(names)}")
        stage: dict = {}
        for field, text_value in zip(names, fields):
            if effect == "delay" and field == "time":
                unit = "beats" if text_value.lower().endswith("q") else "seconds"
                stage[unit] = float(text_value.rstrip("qQsS"))
            else:
                stage[field] = float(text_value)
        if effect == "peak":
            spec.setdefault("peak", []).append(stage)
        else:
            spec[effect] = stage or True
    return spec


def _number(effect: str, field: str, value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{effect} {field} must be a number, not {value!r}") from error
    low, high = FX_RANGES.get(field, (-1e9, 1e9))
    if not low <= number <= high:
        raise ValueError(f"{effect} {field} must be between {low:g} and {high:g}, not {number:g}")
    return number


def _resolve_stage(effect: str, value, bpm: float | None) -> dict:
    defaults = FX_FIELDS[effect]
    first = next(iter(defaults))
    if value is True:
        value = {}
    elif not isinstance(value, dict):
        value = {"seconds" if effect == "delay" else first: value}
    allowed = set(defaults) | ({"seconds", "beats"} if effect == "delay" else set())
    unknown = set(value) - allowed - {"time"}
    if unknown:
        raise ValueError(
            f"{effect} has unknown settings {sorted(unknown)}; allowed: {sorted(allowed)}"
        )
    stage: dict = {"effect": effect}
    for field, default in defaults.items():
        if field == "time":
            continue
        if field not in value and default is None:
            raise ValueError(f"{effect} needs {field}")
        stage[field] = _number(effect, field, value.get(field, default))
    if effect in {"highpass", "lowpass"}:
        if stage["slope"] not in {6, 12, 18, 24}:
            raise ValueError(f"{effect} slope must be 6, 12, 18 or 24 dB/octave")
        stage["slope"] = int(stage["slope"])
    if effect == "delay":
        if "beats" in value:
            if not bpm:
                raise ValueError("A delay in beats needs bpm")
            stage["beats"] = _number(effect, "beats", value["beats"])
            stage["seconds"] = _number(effect, "seconds", stage["beats"] * 60.0 / bpm)
        else:
            stage["seconds"] = _number(effect, "seconds", value.get("seconds", value.get("time")))
    return stage


def resolve_chain(spec, bpm: float | None = None) -> list[dict]:
    """Validate an fx spec (dict or chain string) into ordered stages with every setting."""
    if not spec:
        return []
    if isinstance(spec, str):
        spec = parse_chain(spec)
    if not isinstance(spec, dict):
        raise ValueError('fx must be an object like {"highpass": 120} or a string like "hp=120"')
    chosen: dict = {}
    for label, value in spec.items():
        effect = FX_ALIASES.get(str(label).lower())
        if not effect:
            raise ValueError(f"Unknown effect {label!r}; effects are {', '.join(FX_ORDER)}")
        chosen[effect] = value
    stages = []
    for effect in FX_ORDER:
        value = chosen.get(effect)
        if value is None or value is False:
            continue
        values = value if effect == "peak" and isinstance(value, list) else [value]
        stages += [_resolve_stage(effect, item, bpm) for item in values]
    return stages


def _pan_gains(position: float) -> np.ndarray:
    """Balance pan: centre leaves both sides at unity, hard left silences the right."""
    return np.array([min(1.0, 1.0 - position), min(1.0, 1.0 + position)], dtype=np.float32)


def _plugins(pedalboard, stage: dict) -> list:
    effect = stage["effect"]
    if effect in {"highpass", "lowpass"}:
        kind = pedalboard.HighpassFilter if effect == "highpass" else pedalboard.LowpassFilter
        # Each first-order stage rolls off 6 dB/octave.
        return [kind(cutoff_frequency_hz=stage["hz"]) for _ in range(stage["slope"] // 6)]
    if effect in {"low_shelf", "high_shelf", "peak"}:
        kind = {
            "low_shelf": pedalboard.LowShelfFilter,
            "high_shelf": pedalboard.HighShelfFilter,
            "peak": pedalboard.PeakFilter,
        }[effect]
        return [kind(cutoff_frequency_hz=stage["hz"], gain_db=stage["db"], q=stage["q"])]
    if effect == "compress":
        compressor = pedalboard.Compressor(
            threshold_db=stage["threshold_db"],
            ratio=stage["ratio"],
            attack_ms=stage["attack_ms"],
            release_ms=stage["release_ms"],
        )
        makeup = [pedalboard.Gain(gain_db=stage["makeup_db"])] if stage["makeup_db"] else []
        return [compressor, *makeup]
    if effect == "delay":
        return [
            pedalboard.Delay(
                delay_seconds=stage["seconds"], feedback=stage["feedback"], mix=stage["mix"]
            )
        ]
    if effect == "reverb":
        return [
            pedalboard.Reverb(
                room_size=stage["room"],
                damping=stage["damping"],
                wet_level=stage["wet"],
                dry_level=stage["dry"],
                width=stage["width"],
            )
        ]
    raise ValueError(f"{effect} is not a pedalboard effect")


def _window_min(values: np.ndarray, width: int) -> np.ndarray:
    """min(values[n : n + width]) for every n (past the end counts as 1), in O(n log width)."""
    level, span = np.concatenate([values, np.ones(width, dtype=values.dtype)]), 1
    while span * 2 <= width:
        level = np.minimum(level[:-span], level[span:])
        span *= 2
    return np.minimum(level[: len(values)], level[width - span : width - span + len(values)])


def limit(
    audio: np.ndarray,
    ceiling_db: float = -1.0,
    release_ms: float = 100.0,
    lookahead_ms: float = 5.0,
) -> np.ndarray:
    """Lookahead brickwall peak limiter: no sample exceeds `ceiling_db`; stereo-linked.

    Gain ramps down over the lookahead before each peak and recovers exponentially over
    `release_ms`. Material below the ceiling passes at unity gain.
    """
    if not len(audio):
        return audio
    ceiling = 10 ** (ceiling_db / 20)
    peak = np.abs(audio).max(axis=1).astype(np.float64)
    wanted = np.minimum(1.0, ceiling / np.maximum(peak, 1e-12))
    width = max(int(SAMPLE_RATE * lookahead_ms / 1000), 1)
    hold = _window_min(wanted, width)
    block = 32
    lows = np.concatenate([hold, np.ones(-len(hold) % block)]).reshape(-1, block).min(axis=1)
    recover = float(np.exp(-block / (SAMPLE_RATE * release_ms / 1000)))
    envelope, level = np.empty_like(lows), 1.0
    for index, low in enumerate(lows.tolist()):
        level = min(low, 1.0 - (1.0 - level) * recover)
        envelope[index] = level
    stepped = np.repeat(envelope, block)[: len(hold)]
    # A causal moving average over the lookahead turns steps into ramps; every value it
    # averages is at most the gain the current sample needs, so peaks stay under the ceiling.
    sums = np.cumsum(np.concatenate([np.full(width, stepped[0]), stepped]))
    gain = (sums[width:] - sums[:-width]) / width
    return (audio * gain[:, None]).astype(np.float32)


def apply_chain(audio: np.ndarray, stages: list[dict]) -> np.ndarray:
    """Run resolved stages over (frames, 2) audio. Gain, pan and limit need no pedalboard."""
    result, pending = np.asarray(audio, dtype=np.float32), []

    def flush(signal: np.ndarray) -> np.ndarray:
        if not pending:
            return signal
        pedalboard = _pedalboard()
        board = pedalboard.Pedalboard([p for stage in pending for p in _plugins(pedalboard, stage)])
        pending.clear()
        return board(np.ascontiguousarray(signal.T), float(SAMPLE_RATE)).T

    for stage in stages:
        if stage["effect"] == "gain_db":
            result = flush(result) * np.float32(10 ** (stage["db"] / 20))
        elif stage["effect"] == "pan":
            result = flush(result) * _pan_gains(stage["position"])
        elif stage["effect"] == "limit":
            settings = {k: stage[k] for k in ("ceiling_db", "release_ms", "lookahead_ms")}
            result = limit(flush(result), **settings)
        else:
            pending.append(stage)
    return np.ascontiguousarray(flush(result), dtype=np.float32)


def _pedalboard_version(*chains: list[dict]) -> str | None:
    if any(s["effect"] not in {"gain_db", "pan", "limit"} for chain in chains for s in chain):
        return _pedalboard().__version__
    return None


def apply_fx(
    source: str | Path,
    output: str | Path,
    chain,
    bpm: float | None = None,
    tail: float = 0.0,
) -> dict:
    """Run an effect chain over one file, e.g. a stem or a finished mix.

    `tail` appends seconds of silence so reverb and delay can ring out. Output that
    would clip is scaled to -1 dBFS.
    """
    path, target = Path(source), Path(output)
    tempo = bpm or suno_bpm(path)
    stages = resolve_chain(chain, tempo)
    if not stages:
        raise ValueError("Give at least one effect")
    if not 0 <= tail <= 30:
        raise ValueError("tail must be between 0 and 30 seconds")
    audio = decode(path)
    audio = np.pad(audio, ((0, int(tail * SAMPLE_RATE)), (0, 0)))
    processed = apply_chain(audio, stages)
    peak = float(np.abs(processed).max()) if len(processed) else 0.0
    scaled = peak > SAFE_PEAK
    if scaled:
        processed = _normalize(processed)
    entry = write_wav(target, processed)
    settings = {
        "bpm": tempo,
        "chain": stages,
        "tail": tail,
        "peak_dbfs_before_safety": _dbfs(peak),
        "scaled_to_avoid_clipping": scaled,
        "pedalboard": _pedalboard_version(stages),
    }
    return _write_manifest(
        target.parent, f"fx-{_slug(target.stem)}", settings, _source_info(path), [entry]
    )


PLACEMENT_KEYS = set("sample at unit gain_db repeat every pan fx track note".split())
NOTE_TEXT = re.compile(r"^([A-G])([#b]?)(-?\d)$", re.IGNORECASE)


def midi_note(value) -> int:
    """A MIDI number, or a name where C3 is 60 as in Ableton Live and Logic Pro."""
    if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
        match = NOTE_TEXT.match(value.strip())
        if not match:
            raise ValueError(f"Unknown note {value!r}; use a MIDI number or a name like C3")
        pitch = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[match[1].upper()]
        pitch += {"#": 1, "b": -1}.get(match[2], 0)
        number = pitch + 12 * (int(match[3]) + 2)
    else:
        number = int(value)
    if not 0 <= number <= 127:
        raise ValueError(f"MIDI note {value!r} is outside 0-127")
    return number


def _mixdown(
    placements: list[dict],
    bpm: float | None,
    beats_per_bar: int,
    bars: float | None,
    seconds: float | None,
    base: str | Path | None,
    base_gain_db: float,
    master,
) -> dict:
    """Render placements into per-track buffers and a mastered mix."""

    def to_seconds(value: float, unit: str) -> float:
        if unit == "second":
            return float(value)
        if not bpm:
            raise ValueError(f"Placements in {unit}s need bpm")
        beat = 60.0 / bpm
        return float(value) * (beat * beats_per_bar if unit == "bar" else beat)

    decoded: dict[str, np.ndarray] = {}
    names: dict[str, str] = {}
    items = []
    for index, placement in enumerate(placements, 1):
        if not isinstance(placement, dict) or "sample" not in placement:
            raise ValueError(f"Placement {index} needs a 'sample'")
        unknown = set(placement) - PLACEMENT_KEYS
        if unknown:
            raise ValueError(
                f"Placement {index} has unknown keys {sorted(unknown)}; "
                f"allowed: {sorted(PLACEMENT_KEYS)}"
            )
        sample = str(placement["sample"])
        if sample not in decoded:
            decoded[sample] = decode(sample)
            stem = _slug(Path(sample).stem)
            name, n = stem, 2
            while name in names.values():
                name, n = f"{stem}-{n}", n + 1
            names[sample] = name
        unit = placement.get("unit", "bar" if bpm else "second")
        if unit not in {"bar", "beat", "second"}:
            raise ValueError(f"Unknown unit {unit}")
        start = to_seconds(placement.get("at", 0), unit)
        step = to_seconds(placement.get("every", 0), unit)
        repeat = int(placement.get("repeat", 1))
        if start < 0:
            raise ValueError(f"Placement 'at' must not be negative: {placement}")
        if repeat < 1:
            raise ValueError(f"Placement 'repeat' must be at least 1: {placement}")
        if repeat > 1 and step <= 0:
            raise ValueError("A repeated placement needs a positive 'every'")
        pan = float(placement.get("pan", 0))
        if not -1 <= pan <= 1:
            raise ValueError(
                f"Placement 'pan' must be between -1 (left) and 1 (right): {placement}"
            )
        items.append(
            {
                "index": index,
                "sample": sample,
                "track": str(placement.get("track") or names[sample]),
                "starts": [start + n * step for n in range(repeat)],
                "gain_db": float(placement.get("gain_db", 0)),
                "pan": pan,
                "fx": resolve_chain(placement.get("fx"), bpm),
                "note": midi_note(placement.get("note", 60)),
            }
        )
    master_chain = resolve_chain(master, bpm)

    base_audio = decode(base) if base else None
    if seconds is None and bars is not None:
        seconds = to_seconds(bars, "bar")
    if seconds is None:
        ends = [at + len(decoded[i["sample"]]) / SAMPLE_RATE for i in items for at in i["starts"]]
        if base_audio is not None:
            ends.append(len(base_audio) / SAMPLE_RATE)
        seconds = max(ends, default=0.0)
    if seconds <= 0:
        raise ValueError("Nothing to mix")
    frames = int(seconds * SAMPLE_RATE)
    tracks: dict[str, np.ndarray] = {}
    if base_audio is not None:
        tracks["base"] = np.zeros((frames, CHANNELS), dtype=np.float32)
        portion = base_audio[:frames]
        tracks["base"][: len(portion)] += portion * 10 ** (base_gain_db / 20)
    for item in items:
        clip = decoded[item["sample"]]
        track = tracks.setdefault(item["track"], np.zeros((frames, CHANNELS), dtype=np.float32))
        level = np.float32(10 ** (item["gain_db"] / 20)) * _pan_gains(item["pan"])
        # Effects process the placement's own lane, so reverb and delay tails carry across
        # repeats; gain and pan act like the channel fader afterwards.
        lane = np.zeros_like(track) if item["fx"] else track
        for at in item["starts"]:
            begin = int(at * SAMPLE_RATE)
            if begin >= frames:
                continue
            piece = clip[: frames - begin]
            lane[begin : begin + len(piece)] += piece if item["fx"] else piece * level
        if item["fx"]:
            track += apply_chain(lane, item["fx"]) * level

    mix = np.zeros((frames, CHANNELS), dtype=np.float32)
    for audio in tracks.values():
        mix += audio
    mix = apply_chain(mix, master_chain)
    peak = float(np.abs(mix).max())
    scaled = peak > SAFE_PEAK
    if scaled:
        mix = _normalize(mix)
    return {
        "mix": mix,
        "tracks": tracks,
        "items": items,
        "decoded": decoded,
        "names": names,
        "seconds": seconds,
        "master": master_chain,
        "peak": peak,
        "scaled": scaled,
    }


def _mix_settings(mixed: dict, placements, bpm, beats_per_bar, base, base_gain_db) -> dict:
    sources = {s: sha256(Path(s)) for s in mixed["decoded"]}
    if base:
        sources[str(base)] = sha256(Path(base))
    items = mixed["items"]
    return {
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "seconds": round(mixed["seconds"], 4),
        "base": str(base) if base else None,
        "base_gain_db": base_gain_db,
        "placements": placements,
        "events": sum(len(item["starts"]) for item in items),
        "tracks": {
            name: [item["index"] for item in items if item["track"] == name]
            for name in mixed["tracks"]
        },
        "effects": [
            {
                "placement": item["index"],
                "gain_db": item["gain_db"],
                "pan": item["pan"],
                "chain": item["fx"],
            }
            for item in items
            if item["fx"] or item["pan"] or item["gain_db"]
        ],  # fmt: skip
        "master": mixed["master"],
        "pedalboard": _pedalboard_version(mixed["master"], *(item["fx"] for item in items)),
        "peak_dbfs_before_safety": _dbfs(mixed["peak"]),
        "scaled_to_avoid_clipping": mixed["scaled"],
        "source_sha256": sources,
    }


def layer(
    output: str | Path,
    placements: list[dict],
    bpm: float | None = None,
    beats_per_bar: int = 4,
    bars: float | None = None,
    seconds: float | None = None,
    base: str | Path | None = None,
    base_gain_db: float = 0.0,
    master=None,
) -> dict:
    """Mix samples onto a timeline, optionally over a base track such as a score render.

    Each placement: {"sample": path, "at": 0, "unit": "bar"|"beat"|"second",
    "gain_db": 0, "pan": 0, "repeat": 1, "every": <same unit>, "fx": {...},
    "track": name}. Bars and beats are 0-based and need bpm. `fx` and `master` take an
    effect spec (see `resolve_chain`); the master runs after the tracks are summed and
    usually ends with `limit`. Peaks above -1 dBFS are then scaled down rather than clipped.
    """
    target = Path(output)
    mixed = _mixdown(placements, bpm, beats_per_bar, bars, seconds, base, base_gain_db, master)
    entry = write_wav(target, mixed["mix"])
    settings = _mix_settings(mixed, placements, bpm, beats_per_bar, base, base_gain_db)
    return _write_manifest(target.parent, f"layer-{_slug(target.stem)}", settings, None, [entry])


def _vlq(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def write_midi(
    path: Path,
    tracks: list[tuple[str, list[tuple[float, float, int, int]]]],
    bpm: float | None = None,
    beats_per_bar: int = 4,
    ticks_per_beat: int = 480,
) -> dict:
    """Write a type-1 MIDI file: a tempo track, then one track of (start s, length s,
    note, velocity) per name. Without bpm the file runs at 120 BPM."""
    tempo = bpm or 120.0

    def tick(at: float) -> int:
        return max(0, round(at * tempo / 60 * ticks_per_beat))

    def meta(kind: int, data: bytes) -> bytes:
        return bytes([0xFF, kind]) + _vlq(len(data)) + data

    def chunk(events: list[tuple[int, int, bytes]]) -> bytes:
        body, last = [], 0
        for at, _, data in sorted(events, key=lambda event: event[:2]):
            body.append(_vlq(at - last) + data)
            last = at
        body.append(_vlq(0) + meta(0x2F, b""))
        data = b"".join(body)
        return b"MTrk" + struct.pack(">I", len(data)) + data

    conductor = [
        (0, 0, meta(0x03, b"tempo")),
        (0, 0, meta(0x51, round(60_000_000 / tempo).to_bytes(3, "big"))),
        (0, 0, meta(0x58, bytes([beats_per_bar, 2, 24, 8]))),
    ]
    chunks, count = [chunk(conductor)], 0
    for name, notes in tracks:
        events = [(0, 0, meta(0x03, name.encode()[:127]))]
        ordered = sorted(notes)
        for n, (start, length, note, velocity) in enumerate(ordered):
            on, off = tick(start), tick(start + length)
            following = [tick(s) for s, _, other, _ in ordered[n + 1 :] if other == note]
            if following:
                off = min(off, following[0])  # never overlap the same key
            events += [
                (on, 2, bytes([0x90, note, velocity])),
                (max(off, on + 1), 1, bytes([0x80, note, 0])),
            ]
            count += 1
        chunks.append(chunk(events))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), ticks_per_beat) + b"".join(chunks)
    )
    return {
        "path": str(path),
        "bpm": tempo,
        "tracks": len(tracks),
        "notes": count,
        "sha256": sha256(path),
    }


def export_plan(
    output_dir: str | Path,
    placements: list[dict],
    bpm: float | None = None,
    beats_per_bar: int = 4,
    bars: float | None = None,
    seconds: float | None = None,
    base: str | Path | None = None,
    base_gain_db: float = 0.0,
    master=None,
    name: str = "mix",
) -> dict:
    """Write a layer plan as DAW-ready files for Ableton Live or Logic Pro.

    `<out>/<name>.wav` is the mastered mix. `stems/NN-<track>.wav` are 32-bit float,
    full length from 0 s, after placement effects and before the master, so dropping them
    all at bar 1 rebuilds the mix. `placements.mid` has a tempo track and one track of
    notes per stem (default C3 = 60, velocity from gain) to retrigger `samples/` in a sampler.
    """
    out = Path(output_dir)
    mixed = _mixdown(placements, bpm, beats_per_bar, bars, seconds, base, base_gain_db, master)
    outputs = [{"role": "mix", **write_wav(out / f"{_slug(name)}.wav", mixed["mix"])}]
    for number, (track, audio) in enumerate(mixed["tracks"].items(), 1):
        stem = write_wav(out / "stems" / f"{number:02d}-{_slug(track)}.wav", audio, float32=True)
        outputs.append({"role": "stem", "track": track, **stem})
    for sample, audio in mixed["decoded"].items():
        copy = write_wav(out / "samples" / f"{mixed['names'][sample]}.wav", audio)
        outputs.append({"role": "sample", "source": sample, **copy})
    end = mixed["seconds"]
    notes: dict[str, list] = {}
    for item in mixed["items"]:
        length = len(mixed["decoded"][item["sample"]]) / SAMPLE_RATE
        velocity = int(np.clip(round(100 * 10 ** (item["gain_db"] / 20)), 1, 127))
        notes.setdefault(item["track"], []).extend(
            (at, min(length, end - at), item["note"], velocity) for at in item["starts"] if at < end
        )
    midi = write_midi(out / "placements.mid", list(notes.items()), bpm, beats_per_bar)
    outputs.append({"role": "midi", **midi})
    settings = _mix_settings(mixed, placements, bpm, beats_per_bar, base, base_gain_db)
    settings["midi_bpm"] = midi["bpm"]
    settings["stems"] = (
        "32-bit float WAV, 44.1 kHz stereo, starting at 0 s; after placement fx, gain and "
        "pan, before the master chain and safety scaling"
    )
    return _write_manifest(out, "export", settings, None, outputs)


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

    def samples_analyze(
        self,
        source: str,
        bpm: float | None = None,
        beats_per_bar: int = 4,
        offset: float = 0.0,
        chord_beats: float | None = None,
    ) -> dict:
        return analyze(self.path(source), bpm, beats_per_bar, offset, chord_beats)

    def samples_fit(
        self,
        source: str,
        output_dir: str,
        bpm: float | None = None,
        key: str | None = None,
        source_bpm: float | None = None,
        source_key: str | None = None,
        semitones: float | None = None,
        engine: str = "auto",
        name: str | None = None,
    ) -> dict:
        return fit_sample(
            self.path(source),
            self.path(output_dir),
            bpm,
            key,
            source_bpm,
            source_key,
            semitones,
            engine,
            name,
        )

    def samples_fx(
        self,
        source: str,
        output: str,
        chain: dict | str,
        bpm: float | None = None,
        tail: float = 0.0,
    ) -> dict:
        return apply_fx(self.path(source), self.path(output), chain, bpm, tail)

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

    def samples_stems(
        self, source: str, output_dir: str, model: str = "stems", drumkit: bool = False
    ) -> dict:
        from .separate import PRESETS, separate

        if "/" in model or (
            model not in PRESETS and not model.endswith((".ckpt", ".yaml", ".onnx", ".pth"))
        ):
            raise ValueError(f"Unknown separation model {model}")
        return separate(self.path(source), self.path(output_dir), model, drumkit)

    def samples_transcribe(
        self,
        source: str,
        project: str,
        stem: str | None = None,
        bpm: float | None = None,
        offset: float | None = None,
        meter: str | None = None,
        grid: int = 16,
        tracks: int = 1,
        line: str | None = None,
        key: str | None = None,
        title: str | None = None,
        downbeats: str | None = None,
        join_repeats: bool = False,
    ) -> dict:
        from .transcribe import transcribe

        return transcribe(
            self.path(source),
            self.path(project),
            stem=stem,
            bpm=bpm,
            offset=offset,
            meter=meter,
            grid=grid,
            tracks=tracks,
            line=line,
            key=key,
            title=title,
            downbeats=self.path(downbeats) if downbeats else None,
            join_repeats=join_repeats,
        )

    def samples_slice(
        self, source: str, output_dir: str, start: float, end: float, name: str | None = None
    ) -> dict:
        return slice_sample(self.path(source), self.path(output_dir), start, end, name)

    def _confine(self, placements: list[dict]) -> list[dict]:
        return [{**p, "sample": str(self.path(str(p["sample"])))} for p in placements]

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
        master: dict | str | None = None,
    ) -> dict:
        return layer(
            self.path(output),
            self._confine(placements),
            bpm,
            beats_per_bar,
            bars,
            seconds,
            self.path(base) if base else None,
            base_gain_db,
            master,
        )

    def samples_export(
        self,
        output_dir: str,
        placements: list[dict],
        bpm: float | None = None,
        beats_per_bar: int = 4,
        bars: float | None = None,
        seconds: float | None = None,
        base: str | None = None,
        base_gain_db: float = 0.0,
        master: dict | str | None = None,
        name: str = "mix",
    ) -> dict:
        return export_plan(
            self.path(output_dir),
            self._confine(placements),
            bpm,
            beats_per_bar,
            bars,
            seconds,
            self.path(base) if base else None,
            base_gain_db,
            master,
            name,
        )
