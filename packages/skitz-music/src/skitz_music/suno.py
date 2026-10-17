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
import re
import time
from pathlib import Path
from typing import Any

import httpx

CLERK_BASE = "https://clerk.suno.com"
CLERK_JS_VERSION = os.environ.get("SUNO_CLERK_JS_VERSION", "5.15.0")
API_BASE = os.environ.get("SUNO_API_BASE", "https://studio-api.prod.suno.com")
GENERATE_PATH = os.environ.get("SUNO_GENERATE_PATH", "/api/generate/v2-web/")
USER_AGENT = os.environ.get(
    "SUNO_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)

# Friendly names for Suno's internal model ids; any other value is sent unchanged.
MODELS = {
    "v3.5": "chirp-v3-5",
    "v4": "chirp-v4",
    "v4.5": "chirp-auk",
    "v4.5+": "chirp-bluejay",
    "v5": "chirp-crow",
}
DEFAULT_MODEL = os.environ.get("SUNO_MODEL", "v4.5")

DONE, FAILED = {"complete"}, {"error"}

CAPTCHA_MESSAGE = (
    "Suno requires a captcha. A person must open suno.com, create one song by hand, "
    "then retry. If it still fails, save a fresh cookie with `skitz suno login -`."
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
            f"No Suno cookie. Run `skitz suno login -` or set SUNO_COOKIE (file: {path}).",
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


def slim(clip: dict) -> dict:
    meta = clip.get("metadata") or {}
    return {
        "id": clip.get("id"),
        "status": clip.get("status"),
        "title": clip.get("title"),
        "tags": meta.get("tags"),
        "duration": meta.get("duration"),
        "model": clip.get("model_name") or clip.get("major_model_version"),
        "audio_url": clip.get("audio_url") or None,
        "video_url": clip.get("video_url") or None,
        "image_url": clip.get("image_url") or None,
        "lyrics": meta.get("prompt") or None,
        "error": meta.get("error_message") or None,
    }


def build_payload(
    description: str | None = None,
    lyrics: str | None = None,
    tags: str | None = None,
    title: str | None = None,
    negative_tags: str | None = None,
    instrumental: bool = False,
    model: str | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "mv": MODELS.get(model or DEFAULT_MODEL, model or DEFAULT_MODEL),
        "make_instrumental": instrumental,
        "generation_type": "TEXT",
        "token": None,
    }
    if lyrics is not None or tags or title:
        payload.update(prompt="" if instrumental else (lyrics or ""), tags=tags or "")
        payload["title"] = title or ""
        if negative_tags:
            payload["negative_tags"] = negative_tags
    elif description:
        payload.update(gpt_description_prompt=description, prompt="")
    else:
        raise SunoError(
            "usage", "Give a description (simple mode) or lyrics/tags/title (custom mode)."
        )
    return payload


class SunoClient:
    """Clerk session cookie -> short-lived JWT -> Suno studio API."""

    def __init__(self, cookie: str | None = None, transport: httpx.BaseTransport | None = None):
        self.cookie = cookie or load_cookie()
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
                f"Suno rejected the session (HTTP {response.status_code}). Save a fresh cookie.",
            )
        if response.status_code >= 400:
            raise SunoError(
                "api_error", f"Clerk HTTP {response.status_code}", body=response.text[:500]
            )
        return response.json() or {}

    def token(self) -> str:
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
            raise SunoError("auth_expired", "Suno returned no session token. Save a fresh cookie.")
        self._jwt, self._jwt_expiry = jwt, _jwt_expiry(jwt)
        return jwt

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token()}"}
        response = self.http.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            raise SunoError("auth_expired", "Suno rejected the token. Save a fresh cookie.")
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
        return {
            "credits": info.get("total_credits_left"),
            "plan": info.get("subscription_type") or info.get("plan"),
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

    def download(self, clips: list[dict], directory: Path, request: dict | None = None) -> dict:
        """Save mp3s plus a manifest recording the request, clip metadata and hashes."""
        directory.mkdir(parents=True, exist_ok=True)
        files = []
        for clip in clips:
            if not clip.get("audio_url"):
                continue
            name = re.sub(r"[^A-Za-z0-9_-]+", "-", clip.get("title") or "untitled").strip("-")
            path = directory / f"{name or 'untitled'}-{clip['id'][:8]}.mp3"
            digest = hashlib.sha256()
            with self.http.stream("GET", clip["audio_url"]) as response:
                response.raise_for_status()
                with path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
                        digest.update(chunk)
            files.append({"clip_id": clip["id"], "path": str(path), "sha256": digest.hexdigest()})
        manifest = {
            "source": "suno",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request": request,
            "clips": [slim(clip) for clip in clips],
            "files": files,
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return {"directory": str(directory), "files": files}


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
    ) -> dict:
        payload = build_payload(
            description, lyrics, tags, title, negative_tags, instrumental, model
        )
        clips = self.client.generate(payload)
        ids = [clip["id"] for clip in clips]
        if not output_dir:
            return {"status": "submitted", "ids": ids, "clips": [slim(c) for c in clips]}
        return self.suno_wait(ids, output_dir, timeout, request=payload)

    def suno_status(self, ids: list[str]) -> dict:
        return {"clips": [slim(clip) for clip in self.client.feed(ids)]}

    def suno_wait(
        self,
        ids: list[str],
        output_dir: str | None = None,
        timeout: float = 240,
        request: dict | None = None,
    ) -> dict:
        target = self._output(output_dir) if output_dir else None
        clips = self.client.wait(ids, timeout)
        result: dict[str, Any] = {
            "status": "complete",
            "ids": ids,
            "clips": [slim(c) for c in clips],
        }
        if target:
            result.update(self.client.download(clips, target, request))
        if any(clip.get("status") in FAILED for clip in clips):
            result["status"] = "failed"
        return result

    def suno_lyrics(self, prompt: str) -> dict:
        return self.client.lyrics(prompt)
