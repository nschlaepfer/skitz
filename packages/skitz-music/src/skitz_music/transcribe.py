"""Turn audio (usually a stem from `skitz samples stems`) into an editable Skitz score.

Runs Spotify's basic-pitch in its own uv tool environment, like separate.py runs
audio-separator, so its ML stack never enters the Skitz venv. On macOS it uses the
bundled CoreML model. Notes are snapped to a bar grid, reduced to monophonic tracks
with explicit rests, and saved as a new project next to a manifest that records the
source hash, model, grid and every note that was merged or dropped. A transcription
is an estimate: inspect it and compare a render with the source before relying on it.
"""

import csv
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field, replace
from fractions import Fraction
from itertools import groupby
from pathlib import Path

from music21 import key as music21_key
from music21 import note as music21_note
from music21 import pitch, scale, stream

from .analysis import validate_score
from .samples import SAMPLE_RATE, _source_info, decode, estimate_bpm, suno_bpm, write_wav
from .score import Event, Score, Track
from .store import Project, atomic_json

BASIC_PITCH_VERSION = "0.4.0"
# basic-pitch 0.4.0 runs its CoreML model on Python 3.11 (on 3.12 it wants
# tensorflow-macos, which has no 3.12 wheels), and its resampy dependency still
# imports pkg_resources, which setuptools 81 removed. Resolving against a fixed date
# keeps the rest of its dependencies reproducible.
TRANSCRIBER_PYTHON = "3.11"
RESOLVED_BEFORE = "2026-10-01T00:00:00Z"

GRIDS = (4, 8, 12, 16, 24, 32)  # shortest note value; 12 and 24 are triplets
LINES = ("top", "bottom", "loudest")
# A note under half as loud as the one it competes with is treated as an overtone or
# bleed, not a melody note. (basic-pitch's octave ghosts measured at 0.3-0.46 of their
# fundamental; a soft top voice over a loud piano bass at 0.52.)
WEAK = 0.5
MAX_EVENTS = 10000

# General MIDI program, which note wins an overlap, and the MIDI range kept.
STEMS = {
    "vocals": {"program": 53, "line": "loudest", "range": (36, 84)},
    "backing-vocals": {"program": 52, "line": "loudest", "range": (36, 84)},
    "bass": {"program": 33, "line": "bottom", "range": (24, 67)},
    "guitar": {"program": 27, "line": "top", "range": (40, 88)},
    "piano": {"program": 0, "line": "top", "range": (21, 108)},
    "keyboard": {"program": 4, "line": "top", "range": (21, 108)},
    "strings": {"program": 48, "line": "top", "range": (28, 103)},
    "synth": {"program": 81, "line": "top", "range": (21, 108)},
    "brass": {"program": 61, "line": "top", "range": (34, 84)},
    "woodwinds": {"program": 73, "line": "top", "range": (34, 96)},
    "other": {"program": 0, "line": "top", "range": (21, 108)},
}
DEFAULT_STEM = {"program": 0, "line": "top", "range": (21, 108)}
UNPITCHED = {"drums", "percussion", "kick", "snare", "toms", "hh", "ride", "crash"}
ALIASES = {"vocal": "vocals", "voice": "vocals", "keys": "keyboard", "drum": "drums"}


@dataclass(frozen=True)
class Note:
    """A detected note in seconds."""

    start: float
    end: float
    midi: int
    velocity: int


@dataclass(frozen=True)
class GridNote:
    """A note in grid steps from the start of bar 1."""

    start: int
    end: int
    midi: int
    velocity: int
    shift_ms: float = field(default=0.0, compare=False)  # how far quantizing moved the onset


def transcriber_command() -> list[str]:
    override = os.environ.get("SKITZ_TRANSCRIBER")
    if override:
        return shlex.split(override)
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Transcription needs uv to run basic-pitch")
    return [
        uv, "tool", "run", "--quiet", "--python", TRANSCRIBER_PYTHON,
        "--exclude-newer", RESOLVED_BEFORE,
        "--from", f"basic-pitch=={BASIC_PITCH_VERSION}",
        "--with", "setuptools<81",
        "basic-pitch",
    ]  # fmt: skip


def infer_stem(path: Path) -> str | None:
    """The stem a file holds, from names like `bass.wav` or `Song (Backing Vocals).mp3`."""
    words = [ALIASES.get(w, w) for w in re.findall(r"[a-z]+", path.stem.lower())]
    if "backing" in words and "vocals" in words:
        return "backing-vocals"
    return next((w for w in reversed(words) if w in STEMS or w in UNPITCHED), None)


def read_downbeats(path: str | Path) -> dict:
    """BPM, first downbeat and beats per bar from `skitz suno downbeats` JSON."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and data.get("bpm") and data.get("first_downbeat") is not None:
        return data
    from .suno import tempo_from_downbeats

    info = tempo_from_downbeats(data)
    if not info["bpm"]:
        raise ValueError(f"No downbeats in {path}")
    return info


def read_note_events(path: Path) -> list[Note]:
    """Parse basic-pitch's note-event CSV (extra columns are pitch bends)."""
    notes = []
    with path.open(newline="") as handle:
        rows = csv.reader(handle)
        header = next(rows, None)
        if not header or header[:4] != ["start_time_s", "end_time_s", "pitch_midi", "velocity"]:
            raise RuntimeError(f"Unexpected basic-pitch note file header: {header}")
        for row in rows:
            if len(row) < 4:
                continue
            start, end = float(row[0]), float(row[1])
            if end > start:
                notes.append(Note(start, end, int(float(row[2])), int(float(row[3]))))
    return sorted(notes, key=lambda n: (n.start, n.midi))


def detect_notes(
    wav: Path,
    work: Path,
    bpm: float,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    min_note_ms: float = 127.7,
    timeout: float = 1800,
) -> tuple[list[Note], Path, Path | None]:
    """Run basic-pitch on a WAV; return its notes, CSV and MIDI file."""
    out = work / "basic-pitch"
    out.mkdir()
    command = [
        *transcriber_command(),
        "--save-note-events", "--save-midi",
        "--onset-threshold", str(onset_threshold),
        "--frame-threshold", str(frame_threshold),
        "--minimum-note-length", str(min_note_ms),
        "--midi-tempo", str(bpm),
        str(out), str(wav),
    ]  # fmt: skip
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Transcription timed out after {timeout:.0f}s") from error
    if result.returncode != 0:
        raise RuntimeError(f"basic-pitch failed: {(result.stderr or result.stdout)[-1500:]}")
    table = next(out.glob("*.csv"), None)
    if table is None:
        raise RuntimeError(f"basic-pitch wrote no note events: {result.stderr[-1500:]}")
    return read_note_events(table), table, next(out.glob("*.mid"), None)


def _round(value: float) -> int:
    return math.floor(value + 0.5)


def score_origin(notes: list[Note], offset: float, bar_seconds: float, step_seconds: float):
    """Where bar 1 starts, in source seconds: the first downbeat, or whole bars earlier
    when notes come before it (a pickup), so bar lines stay on the source's grid."""
    earliest = min((n.start for n in notes), default=offset)
    lead = offset - step_seconds / 2 - earliest
    return offset - math.ceil(lead / bar_seconds) * bar_seconds if lead > 0 else offset


def quantize(notes: list[Note], origin: float, step_seconds: float) -> tuple[list[GridNote], int]:
    """Snap starts and ends to the nearest grid step; drop (and count) notes under half
    a step."""
    snapped, short = [], 0
    for n in notes:
        start = (n.start - origin) / step_seconds
        end = (n.end - origin) / step_seconds
        if end - start < 0.5:
            short += 1
            continue
        first = _round(start)
        shift = round(abs(start - first) * step_seconds * 1000, 1)
        snapped.append(GridNote(first, max(_round(end), first + 1), n.midi, n.velocity, shift))
    return snapped, short


def onset_shift(notes: list[GridNote], step_seconds: float) -> dict:
    """How far quantizing moved the kept onsets: near zero when the grid fits, about a
    quarter of a step when tempo or offset is wrong."""
    shifts = [n.shift_ms for n in notes]
    return {
        "mean_ms": round(sum(shifts) / len(shifts), 1) if shifts else None,
        "max_ms": max(shifts, default=None),
        "grid_step_ms": round(step_seconds * 1000, 1),
    }


def merge_unisons(notes: list[GridNote], join_repeats: bool = False) -> tuple[list[GridNote], int]:
    """Join overlapping notes of the same pitch (one held note detected twice). With
    `join_repeats`, also join ones that touch, which vibrato often splits off."""
    merged, joined = [], 0
    for _, group in groupby(sorted(notes, key=lambda n: (n.midi, n.start)), key=lambda n: n.midi):
        current = None
        for n in group:
            if current and (n.start < current.end or (join_repeats and n.start == current.end)):
                current = replace(
                    current,
                    end=max(current.end, n.end),
                    velocity=max(current.velocity, n.velocity),
                )
                joined += 1
                continue
            if current:
                merged.append(current)
            current = n
        merged.append(current)
    return sorted(merged, key=lambda n: (n.start, n.midi)), joined


def _rank(line: str):
    return {
        "top": lambda n: (n.midi, n.velocity),
        "bottom": lambda n: (-n.midi, n.velocity),
        "loudest": lambda n: (n.velocity, n.midi),
    }[line]


def melody_line(notes: list[GridNote], line: str) -> tuple[list[GridNote], list[GridNote], dict]:
    """Pick one monophonic line. Returns (line, leftover notes, counts).

    Of notes starting together, the best by `line` wins among those not much quieter
    than the loudest. A note that starts while the line is sounding cuts the sounding
    note short if it outlasts it, or if it ranks higher and is not much quieter;
    otherwise it is left over.
    """
    rank = _rank(line)
    kept: list[GridNote] = []
    leftover: list[GridNote] = []
    counts = {"chord": 0, "overlap": 0, "truncated": 0}
    for _, group in groupby(sorted(notes, key=lambda n: n.start), key=lambda n: n.start):
        group = list(group)
        loudest = max(n.velocity for n in group)
        best = max((n for n in group if n.velocity >= WEAK * loudest), key=rank)
        others = [n for n in group if n is not best]
        leftover += others
        counts["chord"] += len(others)
        if kept and best.start < kept[-1].end:
            current = kept[-1]
            if best.end > current.end or (
                rank(best) > rank(current) and best.velocity >= WEAK * current.velocity
            ):
                kept[-1] = replace(current, end=best.start)
                counts["truncated"] += 1
            else:
                leftover.append(best)
                counts["overlap"] += 1
                continue
        kept.append(best)
    return kept, leftover, counts


def split_lines(notes: list[GridNote], line: str, tracks: int) -> tuple[list[list[GridNote]], dict]:
    """Peel off up to `tracks` monophonic lines, each from what the last one left over."""
    lines, remaining, truncated = [], notes, 0
    counts = {"chord": 0, "overlap": 0}
    while remaining and len(lines) < tracks:
        kept, remaining, counts = melody_line(remaining, line)
        lines.append(kept)
        truncated += counts["truncated"]
    # Only the last pass's leftovers are lost; earlier ones fed the next track.
    dropped = {"chord": counts["chord"], "overlap": counts["overlap"]} if remaining else {}
    return lines, {"truncated": truncated, "dropped": dropped}


def speller(key_name: str):
    """Spell MIDI numbers in a key: scale notes as the key writes them (in minor, with
    the raised 6th and 7th), naturals next, then sharps in sharp keys and flats in
    flat keys."""
    tonic, mode = key_name.split()
    signature = music21_key.Key(tonic, mode)
    names = {p.name for p in signature.getPitches()}
    if signature.mode == "minor":
        tonic_pitch = signature.tonic.name
        names |= {p.name for p in scale.HarmonicMinorScale(tonic_pitch).getPitches()}
        names |= {p.name for p in scale.MelodicMinorScale(tonic_pitch).getPitches()}
    cache: dict[int, str] = {}

    def rank(candidate: pitch.Pitch, plain: pitch.Pitch):
        alter = candidate.accidental.alter if candidate.accidental else 0
        if signature.sharps > 0:
            leaning = alter > 0
        elif signature.sharps < 0:
            leaning = alter < 0
        else:
            leaning = candidate.name == plain.name
        return (candidate.name in names, alter == 0, abs(alter) == 1 and leaning)

    def spell(midi: int) -> str:
        if midi not in cache:
            plain = pitch.Pitch(midi=midi)
            options = [plain, plain.getHigherEnharmonic(), plain.getLowerEnharmonic()]
            options = [p for p in options if p.octave is not None and 0 <= p.octave <= 8]
            cache[midi] = max(options, key=lambda p: rank(p, plain)).nameWithOctave
        return cache[midi]

    return spell


def estimate_key(notes: list[GridNote]) -> str:
    """Krumhansl-Schmuckler key from pitches weighted by length (music21)."""
    sample = stream.Stream()
    for n in notes:
        sample.append(music21_note.Note(n.midi, quarterLength=n.end - n.start))
    found = sample.analyze("key")
    return f"{found.tonic.name} {found.mode}"


def line_events(
    track_id: str,
    notes: list[GridNote],
    bar_steps: int,
    total_steps: int,
    step: Fraction,
    spell,
) -> list[Event]:
    """Notes and explicit rests that fill every bar; notes crossing a bar line are tied."""
    events: list[Event] = []

    def emit(start: int, end: int, midi: int | None):
        pieces, position = [], start
        while position < end:
            stop = min(end, (position // bar_steps + 1) * bar_steps)
            pieces.append((position, stop))
            position = stop
        for index, (begin, finish) in enumerate(pieces):
            tie = None
            if midi is not None and len(pieces) > 1:
                tie = "start" if index == 0 else "stop" if index == len(pieces) - 1 else "continue"
            events.append(
                Event(
                    id=f"{track_id}_{len(events) + 1:04}",
                    offset=str(begin * step),
                    duration=str((finish - begin) * step),
                    pitch=None if midi is None else spell(midi),
                    tie=tie,
                )
            )

    cursor = 0
    for n in notes:
        if n.start > cursor:
            emit(cursor, n.start, None)
        emit(n.start, n.end, n.midi)
        cursor = n.end
    if cursor < total_steps:
        emit(cursor, total_steps, None)
    return events


def _tempo(
    path: Path,
    audio,
    bpm: float | None,
    offset: float | None,
    meter: str | None,
    downbeats: str | Path | None,
) -> dict:
    beats = read_downbeats(downbeats) if downbeats else {}
    if bpm:
        bpm_source = "argument"
    elif beats.get("bpm"):
        bpm, bpm_source = float(beats["bpm"]), "suno_downbeats"
    elif recorded := suno_bpm(path):
        bpm, bpm_source = float(recorded), "recorded"
    else:
        estimated = estimate_bpm(audio)
        if not estimated:
            raise ValueError("Could not estimate a tempo; pass bpm")
        bpm, bpm_source = float(round(estimated)), "estimated"
    if offset is not None:
        offset_source = "argument"
    elif beats.get("first_downbeat") is not None:
        offset, offset_source = float(beats["first_downbeat"]), "suno_downbeats"
    else:
        offset, offset_source = 0.0, "default"
    if offset < 0:
        raise ValueError("offset must not be negative")
    if not meter:
        meter = f"{beats['beats_per_bar']}/4" if beats.get("beats_per_bar") else "4/4"
    return {
        "bpm": bpm,
        "bpm_source": bpm_source,
        "first_downbeat": offset,
        "offset_source": offset_source,
        "meter": meter,
    }


def transcribe(
    source: str | Path,
    project: str | Path,
    stem: str | None = None,
    bpm: float | None = None,
    offset: float | None = None,
    meter: str | None = None,
    grid: int = 16,
    tracks: int = 1,
    line: str | None = None,
    key: str | None = None,
    title: str | None = None,
    program: int | None = None,
    downbeats: str | Path | None = None,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    min_note_ms: float | None = None,
    join_repeats: bool = False,
    timeout: float = 1800,
) -> dict:
    """Transcribe audio into a new Skitz project at `project`.

    Tempo comes from `bpm`, then `downbeats` (JSON from `skitz suno downbeats`), then
    the BPM Skitz recorded for the file or its stems, then an estimate. Bar 1 starts
    at `offset` seconds (the first downbeat; default 0). `grid` is the shortest note
    value (16 = sixteenths, 12 = eighth triplets). Each track is one monophonic line;
    `tracks` > 1 splits chords into more tracks, and `line` picks which overlapping
    note wins (default by stem: lowest for bass, loudest for vocals, else highest).
    `join_repeats` merges same-pitch notes that touch, for vibrato that the model
    splits into repeated notes (it also joins repeats that were meant). `min_note_ms`
    defaults to 3/4 of a grid step, at most basic-pitch's own 127.7 ms, so a fast
    sixteenth is not lost before quantizing.
    """
    path = Path(source).resolve()
    if not path.is_file():
        raise ValueError(f"No audio file at {path}")
    if stem:
        stem = re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-")
        stem = ALIASES.get(stem, stem)
    stem = stem or infer_stem(path)
    if stem in UNPITCHED:
        raise ValueError(f"{stem} is unpitched; cut it with samples hits or loops instead")
    defaults = STEMS.get(stem, DEFAULT_STEM)
    line = line or defaults["line"]
    if line not in LINES:
        raise ValueError(f"line must be one of {', '.join(LINES)}")
    if grid not in GRIDS:
        raise ValueError(f"grid must be one of {', '.join(map(str, GRIDS))}")
    if not 1 <= tracks <= 8:
        raise ValueError("tracks must be between 1 and 8")
    store = Project(project)
    if (store.state / "HEAD.json").exists():
        raise ValueError(f"Project already exists at {store.path}; choose a new folder")

    started = time.monotonic()
    audio = decode(path)
    tempo = _tempo(path, audio, bpm, offset, meter, downbeats)
    # Check meter, key, tempo and program with the score's own rules before the model runs.
    Score(
        meter=tempo["meter"],
        tempo=round(tempo["bpm"]),
        key=key or "C major",
        tracks=(Track(id="check", name="check", program=program or 0, events=()),),
    )
    bar_quarters = Fraction(tempo["meter"]) * 4
    step = Fraction(4, grid)
    if (bar_quarters / step).denominator != 1:
        raise ValueError(f"A {grid} grid does not divide a {tempo['meter']} bar")
    bar_steps = int(bar_quarters / step)
    beat_seconds = 60.0 / tempo["bpm"]
    step_seconds = float(step) * beat_seconds
    if min_note_ms is None:
        min_note_ms = min(127.7, round(750 * step_seconds, 1))
    low, high = defaults["range"]
    base = stem or "melody"
    settings = {
        "onset_threshold": onset_threshold,
        "frame_threshold": frame_threshold,
        "minimum_note_ms": min_note_ms,
    }

    with tempfile.TemporaryDirectory(prefix="skitz-transcribe-") as temporary:
        work = Path(temporary)
        wav = work / "input.wav"
        write_wav(wav, audio)
        detected, table, midi = detect_notes(
            wav, work, tempo["bpm"], onset_threshold, frame_threshold, min_note_ms, timeout
        )
        in_range = [n for n in detected if low <= n.midi <= high]
        if not in_range:
            raise ValueError(
                f"basic-pitch found no notes in {path.name} between MIDI {low} and {high}"
                + (" (is the stem silent?)" if not detected else "")
            )
        origin = score_origin(
            in_range, tempo["first_downbeat"], bar_quarters * beat_seconds, step_seconds
        )
        snapped, too_short = quantize(in_range, origin, step_seconds)
        if not snapped:
            raise ValueError("Every detected note was shorter than half a grid step")
        unison, merged = merge_unisons(snapped, join_repeats)
        lines, reduction = split_lines(unison, line, tracks)
        shift = onset_shift([n for kept in lines for n in kept], step_seconds)
        audio_steps = math.ceil((len(audio) / SAMPLE_RATE - origin) / step_seconds)
        last = max(n.end for kept in lines for n in kept)
        total_steps = max(1, math.ceil(max(last, audio_steps) / bar_steps)) * bar_steps
        score_key = key or estimate_key(unison)
        spell = speller(score_key)
        stem_name = stem.replace("-", " ").title() if stem else "Melody"
        built = []
        for index, kept in enumerate(lines):
            track_id = base if index == 0 else f"{base}-{index + 1}"
            events = line_events(track_id, kept, bar_steps, total_steps, step, spell)
            if len(events) > MAX_EVENTS:
                raise ValueError(
                    f"Track {track_id} needs {len(events)} events (max {MAX_EVENTS}); "
                    "use a coarser grid or a shorter excerpt"
                )
            built.append(
                Track(
                    id=track_id,
                    name=stem_name if len(lines) == 1 else f"{stem_name} {index + 1}",
                    program=defaults["program"] if program is None else program,
                    events=tuple(events),
                )
            )
        score = Score(
            title=(title or f"{path.stem} (transcribed)")[:200],
            meter=tempo["meter"],
            tempo=round(tempo["bpm"]),
            key=score_key,
            tracks=tuple(built),
        )
        validation = validate_score(score)
        if validation["status"] != "passed":
            raise RuntimeError(f"Transcribed score failed validation: {validation['findings']}")
        created = store.create(score)
        raw = store.path / "transcription"
        raw.mkdir(exist_ok=True)
        shutil.copyfile(table, raw / "basic-pitch.csv")
        if midi:
            shutil.copyfile(midi, raw / "basic-pitch.mid")

    dropped = {
        "out_of_range": len(detected) - len(in_range),
        "too_short": too_short,
        **reduction["dropped"],
    }
    warnings = []
    if tempo["bpm_source"] == "estimated":
        warnings.append(
            "Tempo was estimated and may be half or double; pass bpm (or downbeats) if "
            "the bars look wrong."
        )
    if tempo["offset_source"] == "default":
        warnings.append(
            "Bar 1 is assumed to start at 0 s; pass offset (first_downbeat from "
            "suno_downbeats) if bar lines fall off the beat."
        )
    if abs(tempo["bpm"] - round(tempo["bpm"])) > 0.01:
        warnings.append(
            f"Score tempo is rounded to {round(tempo['bpm'])} from {tempo['bpm']} BPM, so "
            "long renders drift against the source."
        )
    if origin < 0:
        warnings.append(
            f"Notes start before the first downbeat, so bar 1 begins {-origin:.3f} s before "
            "the audio; trim that much from a render to line it up with the source."
        )
    track_summary = [
        {
            "id": t.id,
            "notes": len(kept),
            "events": len(t.events),
            "lowest": spell(min(n.midi for n in kept)),
            "highest": spell(max(n.midi for n in kept)),
        }
        for t, kept in zip(built, lines)
    ]
    notes = {
        "detected": len(detected),
        "kept": sum(len(kept) for kept in lines),
        "merged_unisons": merged,
        "truncated": reduction["truncated"],
        "dropped": {name: count for name, count in dropped.items() if count},
    }
    manifest = {
        "operation": "transcribe",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": _source_info(path),
        "stem": stem,
        "model": {
            "name": "basic-pitch",
            "version": BASIC_PITCH_VERSION,
            "python": TRANSCRIBER_PYTHON,
            "resolved_before": RESOLVED_BEFORE,
            "override": os.environ.get("SKITZ_TRANSCRIBER"),
            "settings": settings,
        },
        "tempo": {**tempo, "score_tempo": score.tempo},
        "quantization": {
            "grid": grid,
            "step_quarters": str(step),
            "bar_quarters": str(bar_quarters),
            "score_start_seconds": round(origin, 4),
            "onset_shift": shift,
        },
        "reduction": {
            "line": line,
            "tracks_requested": tracks,
            "join_repeats": join_repeats,
            "weak_ratio": WEAK,
            "midi_range": [low, high],
        },
        "key": {"value": score_key, "source": "argument" if key else "estimated"},
        "notes": notes,
        "score": {
            "revision": created["revision"],
            "measures": total_steps // bar_steps,
            "tracks": track_summary,
        },
        "raw": {
            "note_events": str(raw / "basic-pitch.csv"),
            "midi": str(raw / "basic-pitch.mid") if midi else None,
        },
        "warnings": warnings,
        "seconds_taken": round(time.monotonic() - started, 2),
    }
    atomic_json(store.path / "transcribe-manifest.json", manifest)
    return {
        "status": "created",
        "project": str(store.path),
        "revision": created["revision"],
        "title": score.title,
        "meter": score.meter,
        "tempo": score.tempo,
        "key": score_key,
        "measures": manifest["score"]["measures"],
        "tracks": track_summary,
        "notes": notes,
        "onset_shift": shift,
        "score_start_seconds": round(origin, 4),
        "bpm_source": tempo["bpm_source"],
        "warnings": warnings,
        "manifest": str(store.path / "transcribe-manifest.json"),
    }
