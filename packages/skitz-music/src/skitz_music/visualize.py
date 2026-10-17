"""Spectrum frames for terminal visualizers.

`spectrum_frames()` analyzes a file once (ffmpeg decode, Hann-window FFT, log-spaced
bands, dB scaling, fast attack and slow decay) into levels from 0 to 100 per band
and frame. `skitz play --visualize` draws them as Unicode block bars in the
terminal; the Skitz agent screen draws the same frames from the playback state file.
"""

import os
import sys
import time
from pathlib import Path

import numpy as np

from .samples import SAMPLE_RATE, decode

BLOCKS = " ▁▂▃▄▅▆▇█"
# Magenta to cyan, matching the Skitz loader.
GRADIENT = ((217, 70, 239), (139, 92, 246), (59, 130, 246), (34, 211, 238))


def spectrum_frames(
    source: str | Path, fps: int = 20, bands: int = 32, low: float = 40.0, high: float = 16000.0
) -> dict:
    audio = decode(source).mean(axis=1)
    hop = SAMPLE_RATE // fps
    size = 2048
    if len(audio) < size:
        audio = np.pad(audio, (0, size - len(audio)))
    windows = np.lib.stride_tricks.sliding_window_view(audio, size)[::hop]
    power = np.abs(np.fft.rfft(windows * np.hanning(size), axis=1)) ** 2
    freqs = np.fft.rfftfreq(size, 1 / SAMPLE_RATE)
    edges = np.geomspace(low, min(high, SAMPLE_RATE / 2), bands + 1)
    columns = []
    for start, end in zip(edges, edges[1:]):
        mask = (freqs >= start) & (freqs < end)
        if not mask.any():  # narrow low bands: take the nearest bin
            mask = np.zeros_like(freqs, dtype=bool)
            mask[np.argmin(np.abs(freqs - (start + end) / 2))] = True
        columns.append(power[:, mask].mean(axis=1))
    db = 10 * np.log10(np.stack(columns, axis=1) + 1e-12)
    ceiling = np.percentile(db, 99.5) if db.size else 0.0
    levels = np.clip((db - (ceiling - 60)) / 60, 0, 1)
    smoothed = np.empty_like(levels)
    current = np.zeros(bands)
    for i, frame in enumerate(levels):  # instant attack, smooth fall
        current = np.maximum(frame, current * 0.82)
        smoothed[i] = current
    return {
        "fps": fps,
        "bands": bands,
        "seconds": round(len(audio) / SAMPLE_RATE, 3),
        "frames": (smoothed * 100).round().astype(int).tolist(),
    }


def _color(position: float) -> tuple[int, int, int]:
    position = min(max(position, 0.0), 1.0) * (len(GRADIENT) - 1)
    index = min(int(position), len(GRADIENT) - 2)
    t = position - index
    a, b = GRADIENT[index], GRADIENT[index + 1]
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def render_bars(levels: list[int], height: int = 4, color: bool = True) -> list[str]:
    """Rows of block characters, top row first, for levels from 0 to 100."""
    rows = []
    for row in range(height - 1, -1, -1):
        cells = []
        for column, level in enumerate(levels):
            filled = level / 100 * height - row
            char = BLOCKS[-1] if filled >= 1 else BLOCKS[max(0, int(filled * 8))]
            if color and char != " ":
                r, g, b = _color(column / max(1, len(levels) - 1))
                char = f"\x1b[38;2;{r};{g};{b}m{char}\x1b[0m"
            cells.append(char)
        rows.append("".join(cells))
    return rows


def frame_at(data: dict, elapsed: float) -> list[int] | None:
    index = int(elapsed * data["fps"])
    frames = data["frames"]
    return frames[index] if 0 <= index < len(frames) else None


def animations_enabled() -> bool:
    return os.environ.get("SKITZ_ANIMATIONS", "on").lower() not in {"off", "0", "false", "no"}


def run_terminal(data: dict, process, title: str, height: int = 6, started: float | None = None):
    """Draw the spectrum while `process` plays; returns when it exits."""
    out = sys.stdout
    started = started or time.monotonic()
    color = out.isatty() and not os.environ.get("NO_COLOR")
    lines = height + 1
    out.write("\x1b[?25l" + "\n" * lines)  # hide cursor, reserve space
    try:
        while process.poll() is None:
            elapsed = min(time.monotonic() - started, data["seconds"])
            levels = frame_at(data, elapsed) or [0] * data["bands"]
            rows = render_bars([lv for lv in levels for _ in (0, 1)], height, color)
            clock = f"{int(elapsed // 60)}:{int(elapsed % 60):02d} / "
            total = data["seconds"]
            clock += f"{int(total // 60)}:{int(total % 60):02d}"
            out.write(f"\x1b[{lines}F")
            for row in rows:
                out.write("\x1b[2K  " + row + "\n")
            out.write(f"\x1b[2K  \x1b[2m{title}  {clock}  (Ctrl-C to stop)\x1b[0m\n")
            out.flush()
            time.sleep(1 / data["fps"])
    finally:
        out.write("\x1b[?25h")
        out.flush()
