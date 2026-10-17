"""Suno song generation on the user's own account, through its web session cookie.

Suno has no public API; this uses the private endpoints its web app calls, which can
change without notice. Generation spends the user's Suno credits. A captcha or an
expired session stops with an explicit error for a human to resolve; nothing here
tries to solve or get around a captcha: with `wait_for_captcha`, Skitz opens suno.com
for the person to solve it and only watches Suno's own check until it clears.

Requests are retried with backoff on 429/502/503/504 and network errors. An expired
session is refreshed once from the Skitz Chrome profile (never the everyday one). A
daily credit budget (suno_budget) is checked before every generation.
"""

import base64
import email.utils
import hashlib
import json
import os
import random
import sys
import time
import webbrowser
from collections.abc import Callable
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
    "then retry, or rerun with --wait-for-captcha (MCP: wait_for_captcha) to open "
    "suno.com/create and wait for them. If it still fails, reconnect with "
    "`skitz auth login suno`."
)
CAPTCHA_URL = "https://suno.com/create"
CAPTCHA_POLL = 5.0
CAPTCHA_HANDOFF = (
    "[suno] Suno wants a captcha before it makes more songs. suno.com/create is open in "
    "your browser: create one song there by hand and solve the captcha yourself. Skitz "
    "waits until Suno stops asking (up to {timeout:.0f}s), then retries once."
)

# Transient failures worth another try. Only 429 and 503 are retried for a request that
# spends credits: after a 502/504 or a dropped connection Suno may have taken it.
RETRY_STATUSES = {429, 502, 503, 504}
SAFE_RETRY_STATUSES = {429, 503}
RETRY_TRIES = 3
RETRY_MAX_WAIT = 60.0  # A longer Retry-After is reported instead of waited out.
LIBRARY_PAGE = 20  # Clips per /api/feed/v2 page.

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
    "budget_exceeded": 8,
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


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a Retry-After header (seconds or an HTTP date), if there is one."""
    value = response.headers.get("retry-after", "").strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


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


BUDGET_MESSAGE = (
    "Today's Suno budget is {daily_limit:g} credits, {spent_today:g} are spent and the next "
    "generation costs about {next_cost:g}. A person must raise it (`skitz suno budget set "
    "N` or SKITZ_SUNO_BUDGET) or wait until tomorrow."
)


def check_budget(model: str | None = None) -> dict:
    """Raise `budget_exceeded` if one more generation would pass today's credit limit."""
    from . import suno_budget

    try:
        state = suno_budget.status(model)
    except ValueError as error:
        raise SunoError("usage", str(error)) from None
    if not state["allowed"]:
        raise SunoError("budget_exceeded", BUDGET_MESSAGE.format(**state), budget=state)
    return state


def request_record(payload: dict, bpm: float | None) -> dict:
    """What a download manifest records: the request plus Skitz-only fields."""
    return {**payload, "skitz_bpm": bpm} if bpm else payload


class SunoClient:
    """Clerk session cookie -> short-lived JWT -> Suno studio API."""

    def __init__(
        self,
        cookie: str | None = None,
        transport: httpx.BaseTransport | None = None,
        reconnect: Callable[[], str | None] | None = None,
    ):
        # SUNO_JWT: a short-lived access token (about an hour) instead of a session cookie.
        self.static_jwt = None if cookie else (os.environ.get("SUNO_JWT", "").strip() or None)
        self.cookie = cookie or ("" if self.static_jwt else load_cookie())
        # Only the saved login is refreshed; a cookie passed in (being checked) is not.
        self.can_reconnect = (
            not cookie
            and not self.static_jwt
            and os.environ.get("SKITZ_SUNO_RECONNECT", "1") != "0"
        )
        self.reconnect = reconnect
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

    def _send(self, method: str, url: str, spends: bool = False, **kwargs: Any) -> httpx.Response:
        """One HTTP request, tried up to RETRY_TRIES times with jittered backoff."""
        for attempt in range(RETRY_TRIES):
            last = attempt == RETRY_TRIES - 1
            try:
                response = self.http.request(method, url, **kwargs)
            except httpx.TransportError as error:
                never_sent = isinstance(error, httpx.ConnectError | httpx.ConnectTimeout)
                if last or (spends and not never_sent):
                    raise
                wait, reason = 2.0**attempt, type(error).__name__
            else:
                retryable = SAFE_RETRY_STATUSES if spends else RETRY_STATUSES
                if last or response.status_code not in retryable:
                    return response
                wait, reason = _retry_after(response), f"HTTP {response.status_code}"
                if wait is not None and wait > RETRY_MAX_WAIT:
                    return response
                wait = 2.0**attempt if wait is None else wait
            wait += random.uniform(0, 1)
            print(f"[suno] {reason}; retrying in {wait:.1f}s", file=sys.stderr)
            self.sleep(wait)
        raise AssertionError("unreachable")

    def _clerk(self, method: str, path: str) -> dict:
        response = self._send(
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

    def _reconnect(self) -> bool:
        """Re-read the Skitz Chrome profile's Suno cookie once; True if it works."""
        if not self.can_reconnect:
            return False
        if self.reconnect is None:
            from .browser_login import refresh_cookie

            self.reconnect = refresh_cookie
        print("[suno] session expired; re-reading the Skitz Chrome profile", file=sys.stderr)
        cookie = self.reconnect()
        if not cookie or cookie == self.cookie:
            return False
        previous = self.cookie
        self.cookie, self.session_id, self._jwt, self._jwt_expiry = cookie, None, None, 0.0
        try:
            self.token()
        except SunoError:
            self.cookie = previous
            return False
        save_cookie(cookie)
        print("[suno] reconnected with the Skitz Chrome profile's session", file=sys.stderr)
        return True

    def request(self, method: str, path: str, spends: bool = False, **kwargs: Any) -> Any:
        try:
            return self._request(method, path, spends, **kwargs)
        except SunoError as error:
            if error.kind != "auth_expired" or not self._reconnect():
                raise
        return self._request(method, path, spends, **kwargs)

    def _request(self, method: str, path: str, spends: bool = False, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token()}"}
        response = self._send(method, f"{API_BASE}{path}", spends, headers=headers, **kwargs)
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
            extra = {"retry_after": _retry_after(response)} if response.status_code == 429 else {}
            message = f"Suno HTTP {response.status_code} on {path}"
            if spends and response.status_code in RETRY_STATUSES - SAFE_RETRY_STATUSES:
                message += (
                    ". Suno may have started it anyway: check `skitz suno library` before "
                    "generating again."
                )
            raise SunoError(
                "api_error",
                message,
                http_status=response.status_code,
                body=body,
                **extra,
            )
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

    def captcha_state(self) -> bool | None:
        """Whether Suno wants a captcha before generating; None if the check failed."""
        try:
            result = self.request("POST", "/api/c/check", json={"ctype": "generation"}) or {}
        except SunoError as error:
            if error.kind in {"auth_expired", "auth_missing"}:
                raise
            return None
        return bool(result.get("required"))

    def captcha_required(self) -> bool:
        # An unavailable check counts as no; the generate call reports a captcha itself.
        return bool(self.captcha_state())

    def wait_for_captcha(
        self,
        timeout: float = 900,
        interval: float = CAPTCHA_POLL,
        opener: Callable[[str], Any] | None = None,
    ) -> None:
        """Open suno.com/create for the person to solve Suno's captcha, and wait until
        Suno's check stops asking for one. Skitz never touches the captcha itself."""
        (opener or webbrowser.open)(CAPTCHA_URL)
        print(CAPTCHA_HANDOFF.format(timeout=timeout), file=sys.stderr)
        deadline = time.monotonic() + timeout
        while self.captcha_state() is not False:
            if time.monotonic() >= deadline:
                raise SunoError(
                    "captcha_required",
                    f"Suno still asks for a captcha after {timeout:.0f}s. A person must "
                    f"create one song by hand at {CAPTCHA_URL}, then retry.",
                    url=CAPTCHA_URL,
                )
            self.sleep(interval)

    def generate(
        self,
        payload: dict,
        request: dict | None = None,
        output_dir: Path | None = None,
        wait_for_captcha: bool = False,
        captcha_timeout: float = 900,
    ) -> list[dict]:
        """Start a generation (2 clips) inside the daily budget, and record it.

        The request goes to requests.jsonl and jobs.json (with `output_dir`, where its
        audio should be saved), and the credits spent to spend.jsonl. With
        `wait_for_captcha`, a captcha opens suno.com/create for the person and this
        retries once after Suno stops asking.
        """
        from . import suno_budget, suno_jobs
        from .suno_inbox import remember_request

        check_budget(payload.get("mv"))
        try:
            clips, before = self._submit(payload)
        except SunoError as error:
            if error.kind != "captcha_required" or not wait_for_captcha:
                raise
            self.wait_for_captcha(captcha_timeout)
            clips, before = self._submit(payload)
        ids = [clip["id"] for clip in clips]
        remember_request(ids, request or payload)
        suno_jobs.add(ids, request or payload, output_dir)
        try:
            after = self._credits()
        except SunoError:
            after = None
        suno_budget.record(ids, payload.get("mv"), before, after)
        return clips

    def _credits(self) -> float | None:
        try:
            credits = self.billing().get("credits")
        except SunoError as error:
            if error.kind in {"auth_expired", "auth_missing"}:
                raise
            return None
        return float(credits) if isinstance(credits, int | float) else None

    def _submit(self, payload: dict) -> tuple[list[dict], float | None]:
        """Send the generate request; returns the clips and the credits before it."""
        if self.captcha_required():
            raise SunoError("captcha_required", CAPTCHA_MESSAGE)
        before = self._credits()
        data = self.request("POST", GENERATE_PATH, spends=True, json=payload) or {}
        clips = data.get("clips") or []
        if not clips:
            raise SunoError("api_error", "Suno accepted the request but returned no clips.")
        return clips, before

    def feed(self, ids: list[str]) -> list[dict]:
        by_id = {}
        for start in range(0, len(ids), 50):  # Keep the query string short.
            chunk = ids[start : start + 50]
            data = self.request("GET", "/api/feed/v2", params={"ids": ",".join(chunk)})
            clips = data.get("clips", []) if isinstance(data, dict) else (data or [])
            by_id.update({clip.get("id"): clip for clip in clips})
        return [by_id.get(clip_id, {"id": clip_id, "status": "unknown"}) for clip_id in ids]

    def library(
        self, search: str | None = None, limit: int = 20, pages: int = 25, stems: bool = False
    ) -> list[dict]:
        """The account's songs, newest first, without trashed clips (and without stems
        unless `stems`). With `search`, only those whose title or style contains it
        (case-insensitive), looking through up to `pages` feed pages of 20 clips."""
        wanted = (search or "").strip().lower()
        found: list[dict] = []
        for page in range(pages):
            data = self.request("GET", "/api/feed/v2", params={"page": page})
            clips = _items(data)
            for clip in clips:
                meta = clip.get("metadata") or {}
                if clip.get("is_trashed") or (meta.get("stem_from_id") and not stems):
                    continue
                text = f"{clip.get('title') or ''} {meta.get('tags') or ''}"
                if not wanted or wanted in text.lower():
                    found.append(clip)
            more = data.get("has_more") if isinstance(data, dict) else None
            if len(found) >= limit or more is False or len(clips) < LIBRARY_PAGE:
                break
        return found[:limit]

    def wait(self, ids: list[str], timeout: float = 600, interval: float = 5) -> list[dict]:
        deadline = time.time() + timeout
        while True:
            clips = self.feed(ids)
            settled = all(clip.get("status") in DONE | FAILED for clip in clips)
            if settled and all(c.get("audio_url") for c in clips if c.get("status") in DONE):
                from .suno_jobs import note_clips

                note_clips(clips)
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
            # Clips imported into this folder before are reused, even if the user has
            # since removed the original from ~/Downloads.
            previous = suno_inbox.previous_imports(directory, [clip["id"] for clip in restricted])
            files += list(previous.values())
            needed = [clip for clip in restricted if clip["id"] not in previous]
            if needed and wait_for_browser:
                matches = suno_inbox.wait_for_downloads(
                    needed,
                    timeout,
                    open_pages=open_pages,
                    log=lambda m: print(m, file=sys.stderr),
                )
            else:
                matches = suno_inbox.match(needed, suno_inbox.scan()) if needed else {}
            files += suno_inbox.import_downloads(needed, matches, directory, request)
        suno_inbox.write_manifest(directory, clips, files, request)
        from .suno_jobs import note_download

        note_download(clips, files)
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
        from .suno_budget import status

        return {**self.client.billing(), "budget": status()}

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
        wait_for_captcha: bool = False,
        captcha_timeout: float = 600,
    ) -> dict:
        payload = build_payload(
            description, lyrics, tags, title, negative_tags, instrumental, model, bpm
        )
        target = self._output(output_dir) if output_dir else None
        request = request_record(payload, bpm)
        clips = self.client.generate(payload, request, target, wait_for_captcha, captcha_timeout)
        ids = [clip["id"] for clip in clips]
        if not output_dir:
            return {"status": "submitted", "ids": ids, "clips": [slim(c) for c in clips]}
        return self.suno_wait(ids, output_dir, timeout, request, wait_for_browser)

    def suno_library(self, search: str | None = None, limit: int = 20, stems: bool = False) -> dict:
        return library_listing(self.client, search, limit, stems=stems)

    def suno_jobs(
        self,
        resume: bool = False,
        wait_for_browser: bool = False,
        timeout: float = 300,
        include_closed: bool = False,
    ) -> dict:
        from . import suno_jobs

        if resume:
            return suno_jobs.resume(
                self.client, timeout, wait_for_browser=wait_for_browser, root=self.workspace
            )
        return suno_jobs.listing(self.client, include_closed)

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


def library_listing(
    client: SunoClient,
    search: str | None = None,
    limit: int = 20,
    pages: int = 25,
    stems: bool = False,
) -> dict:
    """Songs on the account (newest first), each marked `downloaded` when its file is
    already in ~/Downloads or the inbox, with the page to download it from otherwise."""
    from .suno_inbox import scan, song_url

    clips = client.library(search, limit, pages, stems)
    downloaded = {entry["clip_id"] for entry in scan() if entry.get("clip_id")}
    songs = []
    for clip in clips:
        song = {**slim(clip), "created_at": clip.get("created_at")}
        stem_of = (clip.get("metadata") or {}).get("stem_from_id")
        if stem_of:
            song["stem_from_id"] = stem_of
        song.update(downloaded=clip.get("id") in downloaded, song_url=song_url(clip["id"]))
        songs.append(song)
    return {"search": search, "count": len(songs), "songs": songs}


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
