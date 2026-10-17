"""Sign in to Suno in a Chrome window that Skitz owns, then keep that session.

Skitz starts Chrome with its own profile (~/.skitz/suno/browser), so it never reads
your everyday browser. It happens in two steps, because Google refuses sign-ins in
a browser with a debugging connection open:

1. A plain Chrome window (no debugging) where you sign in as usual.
2. Once that window is closed, Skitz reopens the same profile headless with a local
   debugging port, reads the auth.suno.com cookies, confirms them with Suno and saves
   them. The profile stays, so later sign-ins are usually just a click.
"""

import json
import os
import select
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
SIGN_IN_URL = "https://suno.com/sign-in"
AUTH_HOST = "auth.suno.com"


def find_chrome() -> str | None:
    override = os.environ.get("SKITZ_CHROME")
    if override:
        return override
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def profile_dir() -> Path:
    default = Path.home() / ".skitz/suno/browser"
    return Path(os.environ.get("SKITZ_SUNO_BROWSER_PROFILE", str(default))).expanduser()


def auth_cookie_header(cookies: list[dict]) -> str | None:
    """The Cookie header Skitz should send to auth.suno.com, once a login exists."""
    mine = [c for c in cookies if c.get("domain", "").lstrip(".").endswith(AUTH_HOST)]
    if not any(c["name"] == "__client" or c["name"].startswith("__client_") for c in mine):
        return None
    if all(c["name"].startswith("__client_uat") for c in mine if c["name"].startswith("__client")):
        return None
    return "; ".join(f"{c['name']}={c['value']}" for c in mine)


class ChromeWindow:
    """A Chrome process with its own profile and a local DevTools connection."""

    def __init__(self, chrome: str, profile: Path, url: str, headless: bool = True):
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "DevToolsActivePort").unlink(missing_ok=True)
        self.process = subprocess.Popen(
            [
                chrome,
                f"--user-data-dir={profile}",
                "--remote-debugging-port=0",
                *(["--headless=new"] if headless else []),
                "--no-first-run",
                "--no-default-browser-check",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.profile = profile
        self.socket = None
        self.next_id = 0

    def connect(self, timeout: float = 20) -> None:
        import websocket

        port_file = self.profile / "DevToolsActivePort"
        deadline = time.monotonic() + timeout
        while not port_file.exists() or len(port_file.read_text().split()) < 2:
            if time.monotonic() > deadline or self.process.poll() is not None:
                raise RuntimeError("Chrome did not start its debugging port")
            time.sleep(0.2)
        port, path = port_file.read_text().split()[:2]
        # Chrome rejects DevTools connections that carry an Origin header it doesn't
        # allow; a local client sends none.
        self.socket = websocket.create_connection(
            f"ws://127.0.0.1:{port}{path}", timeout=10, suppress_origin=True
        )

    def call(self, method: str, **params) -> dict:
        self.next_id += 1
        self.socket.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(message["error"].get("message", "DevTools error"))
                return message.get("result") or {}

    def cookies(self) -> list[dict]:
        return self.call("Storage.getCookies").get("cookies", [])

    def close(self) -> None:
        try:
            if self.socket:
                self.call("Browser.close")
                self.socket.close()
        except Exception:
            pass
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5 if self.socket else 0)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)


def sign_in_window(
    chrome: str,
    profile: Path,
    url: str = SIGN_IN_URL,
    timeout: float = 900,
    on_open: Callable[[], None] = lambda: None,
) -> None:
    """Open a plain Chrome window on the Skitz profile and wait until it is done.

    Done means the window's Chrome quit (Cmd-Q) or the user pressed Enter in the
    terminal, in which case Skitz quits that Chrome itself so its cookies are saved.
    """
    process = subprocess.Popen(
        [chrome, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    on_open()
    deadline = time.monotonic() + timeout
    interactive = sys.stdin.isatty()
    try:
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise TimeoutError("Stopped waiting for the Suno sign-in.")
            if interactive and select.select([sys.stdin], [], [], 0.5)[0]:
                sys.stdin.readline()
                break
            if not interactive:
                time.sleep(0.5)
    finally:
        if process.poll() is None:
            process.terminate()  # a clean quit, so Chrome writes its cookies to disk
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()


def read_auth_cookies(chrome: str, profile: Path) -> str | None:
    """Reopen the profile headless and return its auth.suno.com Cookie header."""
    window = ChromeWindow(chrome, profile, "about:blank", headless=True)
    try:
        window.connect()
        return auth_cookie_header(window.cookies())
    finally:
        window.close()


def wait_for_login(
    accept: Callable[[str], dict | None],
    chrome: str | None = None,
    timeout: float = 900,
    on_waiting: Callable[[], None] = lambda: None,
) -> tuple[str, dict]:
    """Sign in in Skitz's Chrome profile and return (cookie header, account).

    If the profile is already signed in, no window opens at all. `accept(header)`
    returns account info when Suno accepts the session, or None.
    """
    chrome = chrome or find_chrome()
    if not chrome:
        raise RuntimeError("No Chrome, Chromium, Brave or Edge found (set SKITZ_CHROME).")
    profile = profile_dir()
    header = read_auth_cookies(chrome, profile)
    account = accept(header) if header else None
    if account is not None:
        return header, account
    sign_in_window(chrome, profile, timeout=timeout, on_open=on_waiting)
    header = read_auth_cookies(chrome, profile)
    account = accept(header) if header else None
    if account is None:
        raise RuntimeError(
            "Suno doesn't show a signed-in session in the Skitz window yet. Run the command "
            "again and finish signing in before closing it."
        )
    return header, account
