"""Suno song generation on the user's own account, through its web session cookie.

Suno has no public API; this uses the private endpoints its web app calls, which can
change without notice. Generation spends the user's Suno credits. A captcha or an
expired session stops with an explicit error for a human to resolve; nothing here
tries to solve or get around a captcha.
"""

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# suno.com moved its Clerk frontend API from clerk.suno.com to auth.suno.com (October 2026).
CLERK_BASE = os.environ.get("SUNO_CLERK_BASE", "https://auth.suno.com")
CLERK_JS_VERSION = os.environ.get("SUNO_CLERK_JS_VERSION", "5.15.0")
# Host observed from suno.com in October 2026 (it was studio-api.prod.suno.com before).
API_BASE = os.environ.get("SUNO_API_BASE", "https://studio-api-prod.suno.com")
GENERATE_PATH = os.environ.get("SUNO_GENERATE_PATH", "/api/generate/v2-web/")
USER_AGENT = os.environ.get(
    "SUNO_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)

# Friendly names for Suno's internal model ids; any other value is sent unchanged.
# The v6 ids come from /api/billing/info/ (October 2026); `skitz suno models --live`
# lists what the account can use now. Older ids may no longer be accepted.
MODELS = {
    "v6": "chirp-hawk",
    "v6-wild": "chirp-hawk-wild",
    "v6-mini": "chirp-goose",
    "v5": "chirp-crow",
    "v4.5+": "chirp-bluejay",
    "v4.5": "chirp-auk",
    "v4": "chirp-v4",
}
DEFAULT_MODEL = os.environ.get("SUNO_MODEL", "v6")

DONE, FAILED = {"complete"}, {"error"}

CAPTCHA_MESSAGE = (
    "Suno requires a captcha. A person must open suno.com, create one song by hand, "
    "then retry. If it still fails, reconnect with `skitz auth login suno`."
)

# Exit codes for `skitz suno`, so agents can tell who has to act.
EXIT_CODES = {
    "usage": 1,
    "api_error": 2,
    "generation_failed": 2,
    "not_ready": 2,
    "network_error": 2,
    "auth_missing": 3,
    "auth_expired": 3,
    "captcha_required": 4,
    "out_of_credits": 5,
    "timeout": 6,
    "download_restricted": 7,
}


class SunoError(RuntimeError):
    def __init__(self, kind: str, message: str, **details: Any):
        super().__init__(f"{kind}: {message}")
        self.kind, self.message, self.details = kind, message, details

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.kind, 2)

    def report(self) -> dict:
        return {"status": "failed", "error_kind": self.kind, "error": self.message, **self.details}


def cookie_file() -> Path:
    default = Path.home() / ".skitz/suno/cookie"
    return Path(os.environ.get("SKITZ_SUNO_COOKIE_FILE", str(default))).expanduser()


def load_cookie() -> str:
    cookie = os.environ.get("SUNO_COOKIE", "").strip()
    path = cookie_file()
    if not cookie and path.is_file():
        cookie = path.read_text().strip()
    if not cookie:
        raise SunoError(
            "auth_missing",
            f"Suno is not connected. Run `skitz auth login suno` (or set SUNO_COOKIE; file: {path}).",
        )
    return cookie


def save_cookie(cookie: str) -> Path:
    path = cookie_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(cookie.strip())
    return path


def _jwt_expiry(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, ValueError):
        return time.time() + 30


RESTRICTED_MESSAGE = (
    "Suno no longer serves audio to API clients (audio_url is /api/forbidden since October "
    "2026); its Download button builds the file in the browser. Click Download on each page "
    "in song_urls: Skitz picks the files up from ~/Downloads or ~/.skitz/suno/inbox by the "
    "clip id Suno embeds in them. Then rerun, or pass --wait-for-browser (MCP: "
    "wait_for_browser) to open the pages and wait for the files."
)
STEMS_RESTRICTED_MESSAGE = (
    "Suno no longer lets API clients download stems: they come back with audio_url set to "
    "/api/forbidden and are encrypted for the web player. Use Get Stems > Download on "
    "suno.com, or split the song locally with `skitz samples stems`."
)


def audio_source(clip: dict) -> tuple[str, str]:
    """The downloadable audio URL and file extension for a clip."""
    url = clip.get("audio_url") or ""
    if url.endswith("/forbidden"):
        raise SunoError("download_restricted", RESTRICTED_MESSAGE, id=clip.get("id"))
    return url, ".mp3"


def tempo_from_downbeats(data: Any) -> dict:
    """BPM, meter and bar-1 offset from Suno's downbeats ([[seconds, beat_in_bar], ...])."""
    beats = (data or {}).get("downbeats") if isinstance(data, dict) else None
    beats = [b for b in beats or [] if isinstance(b, list | tuple) and b]
    times = [float(b[0]) for b in beats]
    if len(times) < 2:
        return {"bpm": None, "first_downbeat": None, "beats_per_bar": None}
    # The meter is the most common highest beat number before each bar restarts at 1.
    bar_lengths = [
        int(float(prev[1]))
        for prev, cur in zip(beats, beats[1:])
        if len(prev) > 1 and len(cur) > 1 and float(cur[1]) == 1.0
    ]
    beats_per_bar = max(set(bar_lengths), key=bar_lengths.count) if bar_lengths else 4
    gaps = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    beat = gaps[len(gaps) // 2]
    first = next((float(b[0]) for b in beats if len(b) > 1 and float(b[1]) == 1.0), times[0])
    return {
        "bpm": round(60.0 / beat, 2),
        "first_downbeat": round(first, 4),
        "beats_per_bar": beats_per_bar,
        "beats": len(times),
        "confidence": data.get("downbeat_presence_confidence"),
    }


def slim(clip: dict) -> dict:
    meta = clip.get("metadata") or {}
    return {
        "id": clip.get("id"),
        "status": clip.get("status"),
        "title": clip.get("title"),
        "tags": meta.get("tags"),
        "duration": meta.get("duration"),
        "model": clip.get("model_name") or clip.get("major_model_version"),
        "audio_url": None
        if (clip.get("audio_url") or "").endswith("/forbidden")
        else clip.get("audio_url") or None,
        "video_url": clip.get("video_url") or None,
        "image_url": clip.get("image_url") or None,
        "lyrics": meta.get("prompt") or None,
        "error": meta.get("error_message") or None,
    }


def _items(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("clips", "stems", "items", "data", "results"):
            if isinstance(data.get(key), list):
                return _items(data[key])
    return []


def _stem(clip: dict) -> dict:
    meta = clip.get("metadata") or {}
    title = clip.get("title") or ""
    name = meta.get("stem_type_group_name") or (
        title.rsplit("(", 1)[-1].rstrip(")") if title.endswith(")") else None
    )
    name = name.replace("_", " ") if name else None
    return {**slim(clip), "stem": name, "stem_task": meta.get("stem_task"),
            "stem_from_id": meta.get("stem_from_id")}  # fmt: skip


def build_payload(
    description: str | None = None,
    lyrics: str | None = None,
    tags: str | None = None,
    title: str | None = None,
    negative_tags: str | None = None,
    instrumental: bool = False,
    model: str | None = None,
    bpm: float | None = None,
) -> dict:
    """Build the generate request. `bpm` is written into the style so loops line up."""
    tempo = f"{bpm:g} bpm" if bpm else None
    payload: dict[str, Any] = {
        "mv": MODELS.get(model or DEFAULT_MODEL, model or DEFAULT_MODEL),
        "make_instrumental": instrumental,
        "generation_type": "TEXT",
        "token": None,
    }
    if lyrics is not None or tags or title:
        style = ", ".join(part for part in (tags, tempo) if part)
        payload.update(prompt="" if instrumental else (lyrics or ""), tags=style)
        payload["title"] = title or ""
        if negative_tags:
            payload["negative_tags"] = negative_tags
    elif description:
        text = f"{description}, {tempo}" if tempo else description
        payload.update(gpt_description_prompt=text, prompt="")
    else:
        raise SunoError(
            "usage", "Give a description (simple mode) or lyrics/tags/title (custom mode)."
        )
    return payload


def request_record(payload: dict, bpm: float | None) -> dict:
    """What a download manifest records: the request plus Skitz-only fields."""
    return {**payload, "skitz_bpm": bpm} if bpm else payload


class SunoClient:
    """Clerk session cookie -> short-lived JWT -> Suno studio API."""

    def __init__(self, cookie: str | None = None, transport: httpx.BaseTransport | None = None):
        # SUNO_JWT: a short-lived access token (about an hour) instead of a session cookie.
        self.static_jwt = None if cookie else (os.environ.get("SUNO_JWT", "").strip() or None)
        self.cookie = cookie or ("" if self.static_jwt else load_cookie())
        self.http = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": USER_AGENT},
            transport=transport,
            follow_redirects=True,
        )
        self.session_id: str | None = None
        self._jwt: str | None = None
        self._jwt_expiry = 0.0
        self.sleep = time.sleep

    def _clerk(self, method: str, path: str) -> dict:
        response = self.http.request(
            method,
            f"{CLERK_BASE}{path}",
            params={"_clerk_js_version": CLERK_JS_VERSION},
            headers={"Cookie": self.cookie},
        )
        if response.status_code in {401, 403, 404}:
            raise SunoError(
                "auth_expired",
                f"Suno rejected the session (HTTP {response.status_code}). Reconnect with `skitz auth login suno`.",
            )
        if response.status_code >= 400:
            raise SunoError(
                "api_error", f"Clerk HTTP {response.status_code}", body=response.text[:500]
            )
        return response.json() or {}

    def token(self) -> str:
        if self.static_jwt:
            if time.time() >= _jwt_expiry(self.static_jwt):
                raise SunoError(
                    "auth_expired", "SUNO_JWT has expired. Use a fresh token or cookie."
                )
            return self.static_jwt
        # Clerk issues tokens that last about a minute; refresh shortly before expiry.
        if self._jwt and time.time() < self._jwt_expiry - 10:
            return self._jwt
        if not self.session_id:
            client = self._clerk("GET", "/v1/client").get("response") or {}
            self.session_id = client.get("last_active_session_id")
            if not self.session_id:
                raise SunoError("auth_expired", "The cookie has no active Suno session.")
        jwt = self._clerk("POST", f"/v1/client/sessions/{self.session_id}/tokens").get("jwt")
        if not jwt:
            raise SunoError(
                "auth_expired",
                "Suno returned no session token. Reconnect with `skitz auth login suno`.",
            )
        self._jwt, self._jwt_expiry = jwt, _jwt_expiry(jwt)
        return jwt

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token()}"}
        response = self.http.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            raise SunoError(
                "auth_expired", "Suno rejected the token. Reconnect with `skitz auth login suno`."
            )
        if response.status_code >= 400:
            body = response.text[:1000]
            lowered = body.lower()
            if "captcha" in lowered or "token validation" in lowered:
                raise SunoError(
                    "captcha_required", CAPTCHA_MESSAGE, http_status=response.status_code
                )
            if response.status_code == 402 or "credit" in lowered or "insufficient" in lowered:
                raise SunoError("out_of_credits", "Not enough Suno credits.", body=body)
            raise SunoError("api_error", f"Suno HTTP {response.status_code} on {path}", body=body)
        return response.json() if response.content else None

    def billing(self) -> dict:
        info = self.request("GET", "/api/billing/info/") or {}
        plan = info.get("plan")
        return {
            "credits": info.get("total_credits_left"),
            "plan": plan.get("name") if isinstance(plan, dict) else plan,
            "monthly_limit": info.get("monthly_limit"),
            "monthly_usage": info.get("monthly_usage"),
        }

    def captcha_required(self) -> bool:
        try:
            result = self.request("POST", "/api/c/check", json={"ctype": "generation"}) or {}
        except SunoError as error:
            if error.kind in {"auth_expired", "auth_missing"}:
                raise
            return False  # Check unavailable; the generate call reports a captcha itself.
        return bool(result.get("required"))

    def generate(self, payload: dict) -> list[dict]:
        if self.captcha_required():
            raise SunoError("captcha_required", CAPTCHA_MESSAGE)
        clips = (self.request("POST", GENERATE_PATH, json=payload) or {}).get("clips") or []
        if not clips:
            raise SunoError("api_error", "Suno accepted the request but returned no clips.")
        return clips

    def feed(self, ids: list[str]) -> list[dict]:
        data = self.request("GET", "/api/feed/v2", params={"ids": ",".join(ids)})
        clips = data.get("clips", []) if isinstance(data, dict) else (data or [])
        by_id = {clip.get("id"): clip for clip in clips}
        return [by_id.get(clip_id, {"id": clip_id, "status": "unknown"}) for clip_id in ids]

    def wait(self, ids: list[str], timeout: float = 600, interval: float = 5) -> list[dict]:
        deadline = time.time() + timeout
        while True:
            clips = self.feed(ids)
            settled = all(clip.get("status") in DONE | FAILED for clip in clips)
            if settled and all(c.get("audio_url") for c in clips if c.get("status") in DONE):
                return clips
            if time.time() >= deadline:
                raise SunoError(
                    "timeout",
                    f"Clips not finished after {timeout:.0f}s; wait again with the same ids.",
                    clips=[slim(clip) for clip in clips],
                )
            self.sleep(interval)

    def live_models(self) -> list[dict]:
        models = (self.request("GET", "/api/billing/info/") or {}).get("models") or []
        keys = ("name", "external_key", "major_version", "is_default_model", "can_use")
        return [{k: m.get(k) for k in keys} for m in models]

    def stem_pages(self, clip_id: str) -> int:
        """How many stem variants exist for a clip (Suno makes two of each stem)."""
        return int(
            (self.request("GET", f"/api/clip/{clip_id}/stems/pages") or {}).get("pages") or 0
        )

    def stems(self, clip_id: str) -> list[dict]:
        """Stems already made for a clip in the web app, one entry per variant.

        Suno makes two variants of every stem, shown as 1 and 2 in the web app; the API
        pages them from 0. Making stems needs a captcha on suno.com, so it is not
        automated here: start them in the web app (Edit > Get Stems), then read them here.
        """
        sets = []
        for page in range(self.stem_pages(clip_id)):
            data = self.request("GET", f"/api/clip/{clip_id}/stems", params={"page": page})
            items = _items(data)
            if items:
                sets.append({"variant": page + 1, "stems": [_stem(item) for item in items]})
        return sets

    def downbeats(self, clip_id: str) -> Any:
        """Suno's beat grid for a clip, as returned by the web app's endpoint."""
        return self.request("GET", f"/api/gen/{clip_id}/downbeats")

    def lyrics(self, prompt: str, timeout: float = 60) -> dict:
        job = self.request("POST", "/api/generate/lyrics/", json={"prompt": prompt}) or {}
        if not job.get("id"):
            raise SunoError("api_error", "Lyrics request returned no id.", body=job)
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.request("GET", f"/api/generate/lyrics/{job['id']}") or {}
            if result.get("status") == "complete":
                return {"id": job["id"], "title": result.get("title"), "lyrics": result.get("text")}
            if result.get("status") == "error":
                raise SunoError("generation_failed", "Lyrics generation failed.", result=result)
            self.sleep(2)
        raise SunoError("timeout", "Timed out waiting for lyrics.", id=job["id"])

    def download(
        self,
        clips: list[dict],
        directory: Path,
        request: dict | None = None,
        wait_for_browser: bool = False,
        timeout: float = 600,
        open_pages: bool = True,
    ) -> dict:
        """Save finished clips plus a manifest of the request, clip metadata and hashes.

        Clips Suno still serves are fetched. The rest (audio_url /api/forbidden) come from
        the user's own downloads, matched by the clip id Suno embeds; with
        `wait_for_browser`, their song pages are opened and this waits for the files.
        """
        from . import suno_inbox

        directory.mkdir(parents=True, exist_ok=True)
        files, restricted = [], []
        for clip in clips:
            if not clip.get("audio_url"):
                continue
            if clip["audio_url"].endswith("/forbidden"):
                restricted.append(clip)
                continue
            url, extension = audio_source(clip)
            path = directory / suno_inbox.file_name(clip, extension)
            digest = hashlib.sha256()
            with self.http.stream("GET", url) as response:
                response.raise_for_status()
                with path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
                        digest.update(chunk)
            files.append({
                "clip_id": clip["id"], "path": str(path), "sha256": digest.hexdigest(),
                "origin": "suno_cdn", "request": request or suno_inbox.recalled_request(clip["id"]),
            })  # fmt: skip
        if restricted:
            if wait_for_browser:
                matches = suno_inbox.wait_for_downloads(
                    restricted,
                    timeout,
                    open_pages=open_pages,
                    log=lambda m: print(m, file=sys.stderr),
                )
            else:
                matches = suno_inbox.match(restricted, suno_inbox.scan())
            files += suno_inbox.import_downloads(restricted, matches, directory)
        suno_inbox.write_manifest(directory, clips, files, request)
        result = {"directory": str(directory), "files": files}
        saved = {entry["clip_id"] for entry in files}
        missing = [clip["id"] for clip in restricted if clip["id"] not in saved]
        if missing:
            raise SunoError(
                "download_restricted",
                RESTRICTED_MESSAGE,
                missing=missing,
                song_urls=[suno_inbox.song_url(clip_id) for clip_id in missing],
                watching=[str(d) for d in suno_inbox.watch_dirs()],
                **result,
            )
        return result


class SunoService:
    """Workspace-confined Suno operations for the MCP server."""

    def __init__(self, workspace: str | Path, transport: httpx.BaseTransport | None = None):
        self.workspace = Path(workspace).resolve()
        self.transport = transport
        self._client: SunoClient | None = None

    @property
    def client(self) -> SunoClient:
        if self._client is None:
            self._client = SunoClient(transport=self.transport)
        return self._client

    def _output(self, relative: str) -> Path:
        result = (self.workspace / relative).resolve()
        if not result.is_relative_to(self.workspace):
            raise ValueError("Path escapes the music workspace")
        return result

    def suno_credits(self) -> dict:
        return self.client.billing()

    def suno_generate(
        self,
        description: str | None = None,
        lyrics: str | None = None,
        tags: str | None = None,
        title: str | None = None,
        negative_tags: str | None = None,
        instrumental: bool = False,
        model: str | None = None,
        output_dir: str | None = None,
        timeout: float = 240,
        bpm: float | None = None,
        wait_for_browser: bool = False,
    ) -> dict:
        payload = build_payload(
            description, lyrics, tags, title, negative_tags, instrumental, model, bpm
        )
        from .suno_inbox import remember_request

        clips = self.client.generate(payload)
        ids = [clip["id"] for clip in clips]
        request = request_record(payload, bpm)
        remember_request(ids, request)
        if not output_dir:
            return {"status": "submitted", "ids": ids, "clips": [slim(c) for c in clips]}
        return self.suno_wait(ids, output_dir, timeout, request, wait_for_browser)

    def suno_status(self, ids: list[str]) -> dict:
        return {"clips": [slim(clip) for clip in self.client.feed(ids)]}

    def suno_wait(
        self,
        ids: list[str],
        output_dir: str | None = None,
        timeout: float = 240,
        request: dict | None = None,
        wait_for_browser: bool = False,
    ) -> dict:
        target = self._output(output_dir) if output_dir else None
        clips = self.client.wait(ids, timeout)
        result: dict[str, Any] = {
            "status": "complete",
            "ids": ids,
            "clips": [slim(c) for c in clips],
        }
        if target:
            result.update(self.client.download(clips, target, request, wait_for_browser, timeout))
        if any(clip.get("status") in FAILED for clip in clips):
            result["status"] = "failed"
        return result

    def suno_download(
        self,
        ids: list[str],
        output_dir: str,
        wait_for_browser: bool = False,
        timeout: float = 300,
    ) -> dict:
        target = self._output(output_dir)
        clips = self.client.feed(ids)
        not_ready = [clip["id"] for clip in clips if not clip.get("audio_url")]
        if not_ready:
            raise SunoError("not_ready", "Some clips have no audio yet; wait first.", ids=not_ready)
        return self.client.download(clips, target, None, wait_for_browser, timeout)

    def suno_inbox(self) -> dict:
        return inbox_listing()

    def suno_stems(
        self,
        clip_id: str,
        output_dir: str | None = None,
        variant: int = 1,
        only: list[str] | None = None,
    ) -> dict:
        target = self._output(output_dir) if output_dir else None
        return download_stems(self.client, clip_id, target, variant, only)

    def suno_downbeats(self, clip_id: str) -> dict:
        data = self.client.downbeats(clip_id)
        return {"clip_id": clip_id, **tempo_from_downbeats(data), "downbeats": data}

    def suno_lyrics(self, prompt: str) -> dict:
        return self.client.lyrics(prompt)


def inbox_listing() -> dict:
    """Suno downloads found in the watched folders, by clip id."""
    from .suno_inbox import scan, watch_dirs

    found = [entry for entry in scan() if entry.get("clip_id")]
    return {
        "watching": [str(directory) for directory in watch_dirs()],
        "downloads": [
            {"clip_id": e["clip_id"], "path": str(e["path"]), "duration": round(e["duration"], 2)}
            for e in found
        ],
    }


def download_stems(
    client: SunoClient,
    clip_id: str,
    directory: Path | None = None,
    variant: int = 1,
    only: list[str] | None = None,
) -> dict:
    """List a clip's stems; with a directory, save one variant as `<stem>.mp3`."""
    sets = client.stems(clip_id)
    if not sets:
        raise SunoError(
            "not_ready",
            "No stems for this clip yet. Start them on suno.com (Edit > Get Stems), then retry.",
            clip_id=clip_id,
        )
    chosen = next((s for s in sets if s["variant"] == variant), None)
    if chosen is None:
        available = [s["variant"] for s in sets]
        raise SunoError("usage", f"No stem variant {variant}; available: {available}")
    result: dict[str, Any] = {
        "clip_id": clip_id,
        "variants": len(sets),
        "variant": variant,
        "stems": chosen["stems"],
    }
    if directory is not None:
        wanted = {name.lower().replace("_", " ") for name in only or []}
        ready = [
            s
            for s in chosen["stems"]
            if s.get("status") == "complete"
            and (not wanted or (s.get("stem") or "").lower() in wanted)
        ]
        if not ready:
            raise SunoError(
                "not_ready", "Stems are still processing; retry shortly.", clip_id=clip_id
            )
        if all(not s.get("audio_url") for s in ready):
            raise SunoError("download_restricted", STEMS_RESTRICTED_MESSAGE, clip_id=clip_id)
        named = [{**s, "title": s.get("stem") or s.get("title")} for s in ready]
        request = {"stem_from_id": clip_id, "variant": variant}
        result.update(client.download(named, directory, request))
    return result
