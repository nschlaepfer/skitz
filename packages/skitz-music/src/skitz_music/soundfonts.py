"""Install and find the SoundFont Skitz uses to render scores to audio.

`skitz soundfont install` fetches GeneralUser GS by S. Christian Collins from its
author's GitHub repository, pinned to one commit, and checks size and SHA-256 before
keeping it. Its license allows use for private or commercial music; Skitz does not
bundle the file. Renders look for a SoundFont in this order: an explicit path,
SKITZ_SOUNDFONT, then the installed default.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

GENERALUSER_COMMIT = "97049183643d5fc5a9322a69c5b09efb667c6c3a"
GENERALUSER = {
    "name": "GeneralUser GS",
    "version": "2.0.3",
    "author": "S. Christian Collins",
    "homepage": "https://schristiancollins.com/generaluser.php",
    "source": "https://github.com/mrbumpy409/GeneralUser-GS",
    "commit": GENERALUSER_COMMIT,
    "file": "GeneralUser-GS.sf2",
    "url": f"https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/{GENERALUSER_COMMIT}/GeneralUser-GS.sf2",
    "bytes": 32319396,
    "sha256": "9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe",
    "license_url": f"https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/{GENERALUSER_COMMIT}/documentation/LICENSE.txt",
    "license_sha256": "7b32efefdf95ce38a043799f0659853ddc00fbaa14d8c50f0aca16b9b8b405be",
}


def soundfont_dir() -> Path:
    default = Path.home() / ".skitz/soundfonts"
    return Path(os.environ.get("SKITZ_SOUNDFONT_DIR", str(default))).expanduser()


def installed_path() -> Path:
    return soundfont_dir() / GENERALUSER["file"]


def default_soundfont() -> Path | None:
    """SKITZ_SOUNDFONT if it points at a file, else the installed GeneralUser GS."""
    configured = os.environ.get("SKITZ_SOUNDFONT")
    if configured and Path(configured).expanduser().is_file():
        return Path(configured).expanduser()
    return installed_path() if installed_path().is_file() else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(client: httpx.Client, url: str, target: Path, expected_sha: str, size: int | None):
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    written = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with part.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 20):
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if size and sys.stderr.isatty():
                    print(f"\r  {written * 100 // size:3d}% of {size // 1_000_000} MB", end="",
                          file=sys.stderr, flush=True)  # fmt: skip
    if size and sys.stderr.isatty():
        print(file=sys.stderr)
    if (size and written != size) or digest.hexdigest() != expected_sha:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Download of {url} did not match its pinned size and SHA-256")
    part.replace(target)


def install(force: bool = False, transport: httpx.BaseTransport | None = None) -> dict:
    target = installed_path()
    if target.is_file() and not force and _sha256(target) == GENERALUSER["sha256"]:
        return {"status": "already_installed", "path": str(target), **_summary()}
    target.parent.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(120.0, connect=15.0)
    with httpx.Client(timeout=timeout, follow_redirects=True, transport=transport) as client:
        _download(client, GENERALUSER["url"], target, GENERALUSER["sha256"], GENERALUSER["bytes"])
        _download(
            client,
            GENERALUSER["license_url"],
            target.with_name("GeneralUser-GS-LICENSE.txt"),
            GENERALUSER["license_sha256"],
            None,
        )
    (target.parent / "GeneralUser-GS.json").write_text(
        json.dumps(
            {**GENERALUSER, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            indent=2,
        )
    )
    return {"status": "installed", "path": str(target), **_summary()}


def _summary() -> dict:
    keys = ("name", "version", "author", "homepage", "sha256")
    return {key: GENERALUSER[key] for key in keys}


def status() -> dict:
    found = default_soundfont()
    return {
        "soundfont": str(found) if found else None,
        "source": (
            "SKITZ_SOUNDFONT"
            if found and os.environ.get("SKITZ_SOUNDFONT")
            else ("installed" if found else None)
        ),
        "hint": None if found else "Run `skitz soundfont install` to render audio.",
    }
