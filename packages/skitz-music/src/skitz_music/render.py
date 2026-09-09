"""Derived artifacts and credential-free, restricted notation compilation."""

import hashlib
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import wave
from fractions import Fraction
from pathlib import Path

import music21
from music21 import (
    articulations,
    clef,
    instrument,
    key,
    metadata,
    meter,
    note,
    pitch,
    stream,
    tempo,
    tie,
)

from .analysis import validate_score
from .score import Score
from .store import atomic_json


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def to_music21(score: Score) -> stream.Score:
    result = stream.Score()
    result.metadata = metadata.Metadata(title=score.title)
    tonic, mode = score.key.split()
    for track in score.tracks:
        part = stream.Part(id=track.id)
        part.partName = track.name
        voice_instrument = instrument.Instrument()
        voice_instrument.midiProgram = track.program
        part.insert(0, voice_instrument)
        part.insert(0, meter.TimeSignature(score.meter))
        part.insert(0, tempo.MetronomeMark(number=score.tempo))
        part.insert(0, key.Key(tonic, mode))
        part.insert(0, clef.BassClef() if track.id in {"tenor", "bass"} else clef.TrebleClef())
        for event in track.events:
            item = note.Note(event.pitch) if event.pitch else note.Rest()
            item.id = event.id
            item.duration.quarterLength = Fraction(event.duration)
            if event.tie:
                item.tie = tie.Tie(event.tie)
            if event.articulation:
                item.articulations.append(
                    {
                        "staccato": articulations.Staccato,
                        "tenuto": articulations.Tenuto,
                        "accent": articulations.Accent,
                    }[event.articulation]()
                )
            part.insert(Fraction(event.offset), item)
        result.insert(0, part)
    return result


def lily_pitch(value: str) -> str:
    parsed = pitch.Pitch(value)
    accidental = int(parsed.accidental.alter) if parsed.accidental else 0
    suffix = "is" * accidental if accidental >= 0 else "es" * -accidental
    octave = parsed.octave - 3
    return parsed.step.lower() + suffix + ("'" * octave if octave >= 0 else "," * -octave)


def lilypond_source(score: Score) -> str:
    tonic, mode = score.key.split()
    lily_key = lily_pitch(tonic.upper() + "3")
    parts = []
    names = {}
    for index, track in enumerate(score.tracks):
        name = "voice" + chr(ord("A") + index // 26) + chr(ord("A") + index % 26)
        names[track.id] = name
        tokens = []
        for event in sorted(track.events, key=lambda e: Fraction(e.offset)):
            remaining = Fraction(event.duration)
            position = Fraction(event.offset)
            while remaining:
                length = min(remaining, score.bar_length - position % score.bar_length)
                token = (lily_pitch(event.pitch) if event.pitch else "r") + "4*" + str(length)
                if event.articulation and position == Fraction(event.offset):
                    token += {"staccato": "-.", "tenuto": "--", "accent": "->"}[event.articulation]
                if event.pitch and (remaining > length or event.tie in {"start", "continue"}):
                    token += "~"
                tokens.append(token)
                position += length
                remaining -= length
                if position % score.bar_length == 0:
                    tokens.append("|")
        parts.append(
            f"{name} = {{ \\time {score.meter} \\key {lily_key} \\{mode} "
            f"\\tempo 4 = {score.tempo} " + " ".join(tokens) + " }"
        )
    if set(names) == {"soprano", "alto", "tenor", "bass"}:
        layout = (
            f"\\new PianoStaff << \\new Staff << \\clef treble "
            f"\\new Voice {{ \\voiceOne \\{names['soprano']} }} "
            f"\\new Voice {{ \\voiceTwo \\{names['alto']} }} >> "
            f"\\new Staff << \\clef bass "
            f"\\new Voice {{ \\voiceOne \\{names['tenor']} }} "
            f"\\new Voice {{ \\voiceTwo \\{names['bass']} }} >> >>"
        )
    else:
        layout = "<< " + " ".join(f"\\new Staff {{ \\{name} }}" for name in names.values()) + " >>"
    title = score.title.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return (
        '\\version "2.24.3"\n'
        + f'\\header {{ title = "{title}" tagline = ##f }}\n'
        + "\n".join(parts)
        + f"\n\\score {{ {layout} \\layout {{ }} \\midi {{ }} }}\n"
    )


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024, 128 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


def restricted_run(command: list[str], workspace: Path, timeout: int = 60) -> dict:
    """Fail closed without a supported OS sandbox; no credentials or network."""
    workspace = workspace.resolve()
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        raise RuntimeError(
            "Restricted compilation currently requires macOS sandbox-exec; use a restricted macOS worker"
        )
    roots = [
        "/System",
        "/usr",
        "/bin",
        "/sbin",
        "/opt/homebrew",
        "/Library/Fonts",
        "/private/etc",
        "/private/var/db",
        "/dev",
        str(workspace),
    ]
    read_rules = " ".join(f"(subpath {json.dumps(root)})" for root in roots)
    profile = (
        "(version 1)(allow default)(deny network*)(deny file-read-data file-write*)"
        f'(allow file-read-data (literal "/") {read_rules})'
        f'(allow file-write* (subpath {json.dumps(str(workspace))}) (literal "/dev/null"))'
    )
    env = {
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": str(workspace),
        "TMPDIR": str(workspace),
        "LANG": "en_US.UTF-8",
        "GUILE_AUTO_COMPILE": "0",
    }
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            ["sandbox-exec", "-p", profile, *command],
            cwd=workspace,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=_limits,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        output.seek(0)
        diagnostics = output.read(1024 * 1024).decode(errors="replace")
    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "diagnostics": diagnostics,
        "sandbox": "macos-seatbelt",
        "network": False,
        "credentials": False,
    }


def compile_lilypond(source: str, output_dir: str | Path) -> dict:
    executable = shutil.which("lilypond")
    if not executable:
        raise RuntimeError("LilyPond is not installed")
    if len(source.encode()) > 1024 * 1024:
        raise ValueError("LilyPond input exceeds 1 MiB")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skitz-engrave-") as temporary:
        work = Path(temporary)
        (work / "score.ly").write_text(source)
        report = restricted_run(
            [executable, "-dno-point-and-click", "-o", "score", "score.ly"], work
        )
        for name in ("score.ly", "score.pdf", "score.midi"):
            artifact = work / name
            if artifact.is_file() and not artifact.is_symlink():
                shutil.copyfile(artifact, output_dir / name)
        report["status"] = (
            "passed" if report["exit_code"] == 0 and (work / "score.pdf").is_file() else "failed"
        )
        atomic_json(output_dir / "compiler.json", report)
    return report


def render_score(
    score: Score,
    output_dir: str | Path,
    soundfont: str | None = None,
    audio: bool = True,
    engrave: bool = True,
    sample_rate: int = 44100,
) -> dict:
    validation = validate_score(score)
    if validation["status"] != "passed":
        raise ValueError(f"Cannot render an invalid score: {validation['findings']}")
    if sample_rate not in {22050, 44100, 48000}:
        raise ValueError("Unsupported sample rate")
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=f"{score.revision[:12]}-", dir=destination))
    manifest = {
        "revision": score.revision,
        "status": "passed",
        "artifacts": {},
        "music21_version": music21.__version__,
        "audio_requested": audio,
        "engraving_requested": engrave,
        "sample_rate": sample_rate,
        "output_directory": str(run_dir),
        "errors": [],
    }
    atomic_json(run_dir / "score.json", score.model_dump(mode="json"))
    converted = to_music21(score)
    converted.write("midi", fp=run_dir / "score.mid")
    converted.write("musicxml", fp=run_dir / "score.musicxml")
    source = lilypond_source(score)
    (run_dir / "score.ly").write_text(source)
    if engrave:
        try:
            report = compile_lilypond(source, run_dir)
            manifest["compiler"] = report
            manifest["lilypond_version"] = subprocess.run(
                ["lilypond", "--version"], capture_output=True, text=True, timeout=10
            ).stdout.splitlines()[0]
            if report["status"] != "passed":
                manifest["errors"].append("Notation compilation failed; see compiler diagnostics")
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            manifest["errors"].append(str(exc))
    if audio:
        sf = Path(soundfont or os.environ.get("SKITZ_SOUNDFONT", "")).expanduser()
        executable = shutil.which("fluidsynth")
        if not sf.is_file() or not executable:
            manifest["errors"].append(
                "Audio requires FluidSynth and an explicit SoundFont via --soundfont or SKITZ_SOUNDFONT"
            )
        else:
            manifest["soundfont_sha256"] = sha256(sf)
            manifest["fluidsynth_version"] = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=10
            ).stdout.splitlines()[0]
            manifest["synth_settings"] = {"gain": 0.6, "reverb": False, "chorus": False}
            with tempfile.TemporaryDirectory(prefix="skitz-audio-") as temporary:
                work = Path(temporary)
                shutil.copyfile(sf, work / "instrument.sf2")
                shutil.copyfile(run_dir / "score.mid", work / "score.mid")
                try:
                    report = restricted_run(
                        [
                            executable,
                            "-ni",
                            "-R",
                            "0",
                            "-C",
                            "0",
                            "-g",
                            "0.6",
                            "-r",
                            str(sample_rate),
                            "-T",
                            "wav",
                            "-O",
                            "s16",
                            "-F",
                            "score.wav",
                            "instrument.sf2",
                            "score.mid",
                        ],
                        work,
                    )
                    manifest["audio_renderer"] = report
                    if report["exit_code"] != 0 or not (work / "score.wav").is_file():
                        manifest["errors"].append("Audio render failed")
                    else:
                        shutil.copyfile(work / "score.wav", run_dir / "score.wav")
                        with wave.open(str(run_dir / "score.wav")) as wav:
                            manifest["audio_seconds"] = wav.getnframes() / wav.getframerate()
                except (RuntimeError, OSError) as exc:
                    manifest["errors"].append(str(exc))
    if manifest["errors"]:
        manifest["status"] = "failed"
    manifest["artifacts"] = {
        p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
        for p in sorted(run_dir.iterdir())
        if p.is_file()
    }
    atomic_json(run_dir / "manifest.json", manifest)
    return manifest
