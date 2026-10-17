"""Bring songs downloaded on suno.com into a project.

Suno has no download endpoint for API clients any more: the web app's Download button
builds the file in the browser (October 2026). Every file it makes carries the clip id in
its metadata (`comment=made with suno; created=...; id=<clip id>`), so Skitz finds the
user's downloads by that id in its inbox and ~/Downloads, copies them into the project
with a manifest, and can open the song page and wait for the click. Files without that tag
are matched by title and length, and only when exactly one clip fits.

Skitz never reads the web player's protected stream; it only uses files the user saved.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".mp4"}
CLIP_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# How far a file's length may be from the clip's (encoders pad a little).
DURATION_SLACK = 1.5


def suno_home() -> Path:
    return Path(os.environ.get("SKITZ_SUNO_HOME", str(Path.home() / ".skitz/suno"))).expanduser()


def inbox_dir() -> Path:
    return Path(os.environ.get("SKITZ_SUNO_INBOX", str(suno_home() / "inbox"))).expanduser()


def watch_dirs() -> list[Path]:
    """Where downloads are looked for: SKITZ_SUNO_WATCH (os.pathsep-separated), else the
    Skitz inbox and ~/Downloads."""
    configured = os.environ.get("SKITZ_SUNO_WATCH")
    if configured:
        return [Path(part).expanduser() for part in configured.split(os.pathsep) if part]
    return [inbox_dir(), Path.home() / "Downloads"]


def song_url(clip_id: str) -> str:
    return f"https://suno.com/song/{clip_id}"


# --- requests ledger: what was asked for, so a later import keeps the BPM -------------


def ledger_file() -> Path:
    return suno_home() / "requests.jsonl"


def remember_request(ids: list[str], request: dict) -> None:
    """Record a generate request against its clip ids (append-only)."""
    path = ledger_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ids": ids,
        "request": request,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with path.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")


def recalled_request(clip_id: str) -> dict | None:
    path = ledger_file()
    if not path.is_file():
        return None
    found = None
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if clip_id in entry.get("ids", []):
            found = entry.get("request")
    return found


# --- finding downloads -----------------------------------------------------------------

_probe_cache: dict[tuple[str, int, int], dict | None] = {}


def probe(path: Path) -> dict | None:
    """Duration and embedded Suno clip id of an audio file; None if it is not audio."""
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key in _probe_cache:
        return _probe_cache[key]
    try:
        output = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout  # fmt: skip
        data = json.loads(output).get("format") or {}
    except (OSError, subprocess.SubprocessError, ValueError):
        data = None
    info = None
    if data is not None and data.get("duration") not in (None, "N/A"):
        tags = {str(k).lower(): str(v) for k, v in (data.get("tags") or {}).items()}
        info = {"duration": float(data["duration"]), "clip_id": clip_id_from_tags(tags)}
    _probe_cache[key] = info
    return info


def clip_id_from_tags(tags: dict[str, str]) -> str | None:
    """The clip id Suno writes into downloads (`... id=<uuid>` in the comment)."""
    for value in tags.values():
        if "suno" not in value.lower():
            continue
        tagged = re.search(r"\bid=(" + CLIP_ID.pattern + ")", value)
        if tagged:
            return tagged.group(1)
        bare = CLIP_ID.search(value)
        if bare:
            return bare.group(0)
    return None


def scan(dirs: list[Path] | None = None) -> list[dict]:
    """Audio files in the watched folders, newest first, with duration and clip id."""
    found = []
    for directory in dirs or watch_dirs():
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            # Skip folders, hidden files and downloads still in progress (.crdownload etc.).
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.suffix.lower() not in AUDIO_SUFFIXES
            ):
                continue
            info = probe(path)
            if info:
                found.append({"path": path, "mtime": path.stat().st_mtime, **info})
    return sorted(found, key=lambda entry: entry["mtime"], reverse=True)


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def match(clips: list[dict], found: list[dict]) -> dict[str, dict]:
    """Pick the newest download for each clip: by embedded id, else by title and length."""
    matches: dict[str, dict] = {}
    for entry in found:  # newest first
        clip_id = entry.get("clip_id")
        if clip_id and clip_id not in matches and any(c.get("id") == clip_id for c in clips):
            matches[clip_id] = entry
    for entry in found:
        if entry.get("clip_id"):
            continue  # A tagged file belongs to the clip it names, or to none of these.
        stem = _plain(re.sub(r"\s*\(\d+\)$", "", entry["path"].stem))  # "Title (1).m4a"
        fits = [
            clip for clip in clips
            if clip.get("id") not in matches
            and stem and stem == _plain(clip.get("title") or "")
            and abs(((clip.get("metadata") or {}).get("duration") or -99) - entry["duration"]) <= DURATION_SLACK
        ]  # fmt: skip
        if len(fits) == 1:
            matches[fits[0]["id"]] = entry
    return matches


# --- importing ---------------------------------------------------------------------------


def file_name(clip: dict, suffix: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", clip.get("title") or "untitled").strip("-")
    return f"{name or 'untitled'}-{clip['id'][:8]}{suffix}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    directory: Path, clips: list[dict], files: list[dict], request: dict | None
) -> None:
    """Merge into the folder's manifest.json by clip id, so earlier entries are kept."""
    from .suno import slim

    path = directory / "manifest.json"
    try:
        manifest = json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        manifest = {}
    if manifest.get("source") != "suno":
        manifest = {"source": "suno", "clips": [], "files": []}
    new_ids = {clip["id"] for clip in clips}
    manifest["clips"] = [c for c in manifest.get("clips", []) if c.get("id") not in new_ids]
    manifest["clips"] += [slim(clip) for clip in clips]
    file_ids = {entry["clip_id"] for entry in files}
    kept = [f for f in manifest.get("files", []) if f.get("clip_id") not in file_ids]
    legacy = manifest.get("request")
    if request is not None and legacy is not None and request != legacy:
        # Older manifests kept one request for the whole folder; pin it to their files
        # before the folder-level one changes, so their BPM stays theirs.
        for entry in kept:
            entry.setdefault("request", legacy)
    manifest["files"] = kept + files
    manifest["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if request is not None:
        manifest["request"] = request
    path.write_text(json.dumps(manifest, indent=2))


def previous_imports(directory: Path, clip_ids: list[str]) -> dict[str, dict]:
    """Clips already in this folder's manifest whose file is still there, unchanged."""
    path = directory / "manifest.json"
    try:
        manifest = json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        return {}
    found = {}
    for entry in manifest.get("files", []):
        if entry.get("clip_id") not in clip_ids or entry["clip_id"] in found:
            continue
        for candidate in (
            Path(entry.get("path", "")),
            directory / Path(entry.get("path", "")).name,
        ):
            if candidate.is_file() and sha256(candidate) == entry.get("sha256"):
                found[entry["clip_id"]] = {**entry, "path": str(candidate)}
                break
    return found


def import_downloads(
    clips: list[dict], matches: dict[str, dict], directory: Path, request: dict | None = None
) -> list[dict]:
    """Copy matched downloads into the project; the user's originals stay where they are."""
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for clip in clips:
        entry = matches.get(clip["id"])
        if not entry:
            continue
        source: Path = entry["path"]
        target = directory / file_name(clip, source.suffix.lower())
        shutil.copy2(source, target)
        files.append({
            "clip_id": clip["id"],
            "path": str(target),
            "sha256": sha256(target),
            "origin": "browser_download",
            "downloaded_from": str(source),
            "matched_by": "embedded_id" if entry.get("clip_id") else "title_and_duration",
            "request": request or recalled_request(clip["id"]),
        })  # fmt: skip
    return files


def wait_for_downloads(
    clips: list[dict],
    timeout: float = 600,
    interval: float = 2,
    open_pages: bool = True,
    dirs: list[Path] | None = None,
    opener: Callable[[str], Any] | None = None,
    sleep: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, dict]:
    """Open each missing song's page and wait until its download shows up."""
    opener = opener or webbrowser.open
    sleep = sleep or time.sleep
    matches = match(clips, scan(dirs))
    missing = [clip for clip in clips if clip["id"] not in matches]
    if open_pages:
        for clip in missing:
            opener(song_url(clip["id"]))
    if missing and log:
        titles = ", ".join(f"{c.get('title') or c['id']}" for c in missing)
        log(f"[suno] click Download on suno.com for: {titles} (waiting up to {timeout:.0f}s)")
    deadline = time.monotonic() + timeout
    while missing and time.monotonic() < deadline:
        sleep(interval)
        matches.update(match(missing, scan(dirs)))
        missing = [clip for clip in clips if clip["id"] not in matches]
    return matches
