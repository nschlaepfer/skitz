"""Play renders and other audio on this computer.

`skitz play <project>` plays the newest audio render of the project's current
revision; `skitz play <file>` plays any audio file. Playback uses afplay on macOS,
or ffplay / paplay / aplay elsewhere. One background playback at a time is tracked
so the agent can stop it. While it plays, `~/.skitz/playback.json` holds the file's
spectrum frames so the Skitz agent screen can draw a live visualizer.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aif", ".aiff", ".flac", ".ogg"}


def player_command(path: Path) -> list[str]:
    if shutil.which("afplay"):
        return ["afplay", str(path)]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
    for name in ("paplay", "aplay"):
        if shutil.which(name):
            return [name, str(path)]
    raise RuntimeError("No audio player found (afplay, ffplay, paplay or aplay).")


def latest_render(project: Path) -> Path:
    """The newest score.wav rendered from the project's current revision."""
    from .store import Project

    revision = Project(project).read().revision
    renders = []
    for manifest_file in (project / "renders").rglob("manifest.json"):
        try:
            manifest = json.loads(manifest_file.read_text())
        except ValueError:
            continue
        wav = manifest_file.parent / "score.wav"
        if manifest.get("revision") == revision and wav.is_file():
            renders.append(wav)
    if not renders:
        raise ValueError(
            "No audio render of the current revision yet. Render it first (with a SoundFont "
            "installed: `skitz soundfont install`)."
        )
    return max(renders, key=lambda p: p.stat().st_mtime)


def resolve(target: str | Path) -> Path:
    path = Path(target).expanduser().resolve()
    if path.is_dir() and (path / ".skitz").is_dir():
        return latest_render(path)
    if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
        return path
    raise ValueError(f"Not an audio file or Skitz project: {target}")


def _state_dir() -> Path:
    return Path(os.environ.get("SKITZ_STATE", str(Path.home() / ".skitz")))


def _pid_file() -> Path:
    return _state_dir() / "playback.pid"


def state_file() -> Path:
    return _state_dir() / "playback.json"


def stop() -> dict:
    pid_file = _pid_file()
    state_file().unlink(missing_ok=True)
    if not pid_file.is_file():
        return {"status": "nothing_playing"}
    try:
        os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        status = "stopped"
    except (ProcessLookupError, ValueError):
        status = "nothing_playing"
    pid_file.unlink(missing_ok=True)
    return {"status": status}


def play(target: str | Path, background: bool = False, visualize: bool = False) -> dict:
    path = resolve(target)
    command = player_command(path)
    if background:
        stop()
        # Analyze first so the visualizer and the audio start together.
        from .visualize import animations_enabled, spectrum_frames

        frames = None
        if animations_enabled():
            try:
                frames = spectrum_frames(path)
            except (RuntimeError, ValueError, OSError):
                frames = None
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        started = time.time()
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        _pid_file().write_text(str(process.pid))
        state = {"pid": process.pid, "path": str(path), "title": path.name, "started_at": started}
        if frames:
            state.update(frames)
        temp = state_file().with_suffix(".tmp")
        temp.write_text(json.dumps(state))
        temp.replace(state_file())
        return {"status": "playing", "path": str(path), "pid": process.pid}
    if visualize and sys.stdout.isatty():
        from .visualize import run_terminal, spectrum_frames

        data = spectrum_frames(path)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            run_terminal(data, process, path.name, started=time.monotonic())
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait(timeout=5)
            return {"status": "stopped", "path": str(path)}
        return {"status": "played" if code == 0 else "failed", "path": str(path)}
    code = subprocess.call(command)
    return {"status": "played" if code == 0 else "failed", "path": str(path)}


class PlaybackService:
    """Workspace-confined playback for the MCP server."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def play_audio(self, path: str) -> dict:
        target = (self.workspace / path).resolve()
        if not target.is_relative_to(self.workspace):
            raise ValueError("Path escapes the music workspace")
        return play(target, background=True)

    def stop_audio(self) -> dict:
        return stop()
