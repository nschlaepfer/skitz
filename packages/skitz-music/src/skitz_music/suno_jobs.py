"""Suno generations that outlive the process that started them.

Every generate is recorded in ~/.skitz/suno/jobs.json with its request and the folder its
audio should go to. `skitz suno jobs` shows each open job's live status, and
`skitz suno jobs --resume` (MCP suno_jobs) waits for the clips and downloads them after a
restart, a timeout or a pending browser download.

States: `submitted` (Suno is still making it), `needs_download` (finished, waiting for the
user's Download click), then `done`, `complete` (finished, no folder was asked for),
`failed` or `dismissed`.
"""

import contextlib
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .suno_inbox import suno_home

OPEN = {"submitted", "needs_download"}

try:
    import fcntl
except ImportError:  # Windows: no locking, writes are still atomic.
    fcntl = None


def jobs_file() -> Path:
    return suno_home() / "jobs.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load() -> list[dict]:
    path = jobs_file()
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        data = {}
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return [job for job in jobs or [] if isinstance(job, dict) and job.get("ids")]


@contextlib.contextmanager
def editing() -> Iterator[list[dict]]:
    """Read-modify-write jobs.json under a lock (the CLI and MCP server may share it)."""
    path = jobs_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / "jobs.lock").open("a") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        jobs = load()
        yield jobs
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"jobs": jobs}, indent=2))
        temp.replace(path)


def add(ids: list[str], request: dict, output_dir: Path | None) -> dict:
    title = request.get("title") or request.get("gpt_description_prompt") or ""
    job = {
        "id": ids[0],
        "ids": ids,
        "title": title[:80],
        "request": request,
        "output_dir": str(output_dir) if output_dir else None,
        "state": "submitted",
        "created_at": _now(),
        "updated_at": _now(),
        "files": [],
        "failed": [],
    }
    with editing() as jobs:
        jobs.append(job)
    return job


def find(job_id: str) -> dict | None:
    return next((job for job in load() if job_id in (job["id"], *job["ids"])), None)


def dismiss(job_id: str) -> dict | None:
    with editing() as jobs:
        for job in jobs:
            if job_id in (job["id"], *job["ids"]):
                job.update(state="dismissed", updated_at=_now())
                return job
    return None


def _settle(job: dict, statuses: dict[str, str | None]) -> None:
    from .suno import DONE, FAILED

    job["failed"] = sorted(
        set(job.get("failed") or []) | {i for i in job["ids"] if statuses.get(i) in FAILED}
    )
    saved = {entry["clip_id"] for entry in job.get("files") or []}
    waiting = [i for i in job["ids"] if i not in saved and i not in job["failed"]]
    if job.get("state") not in OPEN:
        return
    if not waiting:
        job["state"] = "done" if saved else "failed"
    elif all(statuses.get(i) in DONE for i in waiting):
        job["state"] = "needs_download" if job.get("output_dir") else "complete"
    job["updated_at"] = _now()


def note_clips(clips: list[dict]) -> None:
    """Update open jobs from clips' latest status (failed clips, finished jobs)."""
    statuses = {clip.get("id"): clip.get("status") for clip in clips}
    if not jobs_file().is_file():
        return
    with editing() as jobs:
        for job in jobs:
            if job.get("state") in OPEN and set(job["ids"]) & set(statuses):
                _settle(job, statuses)


def note_download(clips: list[dict], files: list[dict]) -> None:
    """Record saved files against their jobs; a job is done once each live clip has one."""
    if not jobs_file().is_file():
        return
    statuses = {clip.get("id"): clip.get("status") for clip in clips}
    saved = {entry["clip_id"]: entry["path"] for entry in files}
    with editing() as jobs:
        for job in jobs:
            if not set(job["ids"]) & set(statuses):
                continue
            known = {entry["clip_id"]: entry for entry in job.get("files") or []}
            known.update(
                {i: {"clip_id": i, "path": p} for i, p in saved.items() if i in job["ids"]}
            )
            job["files"] = list(known.values())
            _settle(job, statuses)


# --- listing and resuming (needs a SunoClient) ----------------------------------------------


def _summary(job: dict, clips: dict[str, dict], downloaded: set[str]) -> dict:
    from .suno_inbox import song_url

    saved = {entry["clip_id"]: entry["path"] for entry in job.get("files") or []}
    summary = {k: job.get(k) for k in ("id", "state", "title", "output_dir", "created_at")}
    summary["clips"] = [
        {
            "id": clip_id,
            "status": (clips.get(clip_id) or {}).get("status")
            or ("error" if clip_id in (job.get("failed") or []) else None),
            "title": (clips.get(clip_id) or {}).get("title"),
            "saved_to": saved.get(clip_id),
            "downloaded": clip_id in downloaded,
        }
        for clip_id in job["ids"]
    ]
    if job.get("state") == "needs_download":
        summary["song_urls"] = [
            song_url(c["id"])
            for c in summary["clips"]
            if not c["saved_to"] and c["status"] != "error"
        ]
    return summary


def _downloaded() -> set[str]:
    from .suno_inbox import scan

    return {entry["clip_id"] for entry in scan() if entry.get("clip_id")}


def listing(client: Any, include_closed: bool = False, only: set[str] | None = None) -> dict:
    """Jobs, newest first, with live clip status (open jobs, or `only` these job ids)."""

    def shown(jobs: list[dict]) -> list[dict]:
        if only is not None:
            return [job for job in reversed(jobs) if job["id"] in only]
        return [job for job in reversed(jobs) if include_closed or job.get("state") in OPEN]

    ids = [i for job in shown(load()) for i in job["ids"]]
    clips = {clip["id"]: clip for clip in client.feed(ids)} if ids else {}
    if clips:
        note_clips(list(clips.values()))
    jobs = load()
    listed = shown(jobs)
    downloaded = _downloaded() if any(j.get("state") == "needs_download" for j in listed) else set()
    return {
        "jobs_file": str(jobs_file()),
        "open": sum(job.get("state") in OPEN for job in jobs),
        "jobs": [_summary(job, clips, downloaded) for job in listed],
    }


def resume(
    client: Any,
    timeout: float = 600,
    interval: float = 5,
    wait_for_browser: bool = False,
    open_pages: bool = True,
    root: Path | None = None,
) -> dict:
    """Wait for open jobs and download each into its folder as soon as it finishes.

    `root` confines downloads (the MCP workspace): jobs saving elsewhere are skipped.
    Raises SunoError `download_restricted` if songs still need a Download click, or
    `timeout` if Suno hasn't finished some; both carry every job's state.
    """
    from . import suno_inbox
    from .suno import DONE, FAILED, SunoError

    deadline = time.monotonic() + timeout
    skipped: dict[str, str] = {}
    pending = [job for job in load() if job.get("state") in OPEN]
    if root is not None:
        for job in pending:
            target = job.get("output_dir")
            if target and not Path(target).resolve().is_relative_to(root):
                skipped[job["id"]] = (
                    f"Saves outside the workspace ({target}); resume it with the CLI."
                )
        pending = [job for job in pending if job["id"] not in skipped]
    ready: list[tuple[dict, list[dict]]] = []
    while pending:
        clips = {clip["id"]: clip for clip in client.feed([i for j in pending for i in j["ids"]])}
        waiting = []
        for job in pending:
            mine = [clips[i] for i in job["ids"]]
            settled = all(c.get("status") in DONE | FAILED for c in mine) and all(
                c.get("audio_url") for c in mine if c.get("status") in DONE
            )
            if settled:
                ready.append((job, mine))
            else:
                waiting.append(job)
        pending = waiting
        if not pending or time.monotonic() >= deadline:
            break
        client.sleep(interval)

    for _, mine in ready:
        note_clips(mine)
    downloads = [(job, mine) for job, mine in ready if job.get("output_dir")]
    if wait_for_browser:
        saved = {e["clip_id"] for job, _ in downloads for e in job.get("files") or []}
        restricted = [
            clip
            for _, mine in downloads
            for clip in mine
            if (clip.get("audio_url") or "").endswith("/forbidden") and clip["id"] not in saved
        ]
        if restricted:
            suno_inbox.wait_for_downloads(
                restricted,
                max(0.0, deadline - time.monotonic()),
                open_pages=open_pages,
                log=lambda m: print(m, file=sys.stderr),
            )
    errors: dict[str, dict] = {}
    for job, mine in downloads:
        try:
            client.download(mine, Path(job["output_dir"]), job.get("request"))
        except SunoError as error:
            if error.kind != "download_restricted":
                raise
            errors[job["id"]] = {"error_kind": error.kind, "missing": error.details.get("missing")}

    touched = {job["id"] for job, _ in ready} | {job["id"] for job in pending} | set(skipped)
    result = listing(client, only=touched)
    for job in result["jobs"]:
        if job["id"] in skipped:
            job["skipped"] = skipped[job["id"]]
        job.update(errors.get(job["id"], {}))
    result["status"] = "complete"
    if errors:
        from .suno import RESTRICTED_MESSAGE

        urls = [url for job in result["jobs"] for url in job.get("song_urls") or []]
        raise SunoError("download_restricted", RESTRICTED_MESSAGE, song_urls=urls, **result)
    if pending:
        raise SunoError(
            "timeout",
            f"{len(pending)} job(s) not finished after {timeout:.0f}s; run `skitz suno jobs "
            "--resume` again.",
            **result,
        )
    return result
