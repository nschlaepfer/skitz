"""`skitz auth ...`: sign in to the services Skitz uses, one command per provider.

  skitz auth                 show every provider and whether it is connected
  skitz auth login           pick a provider from a menu
  skitz auth login suno      connect your Suno account (also: skitz login suno)
  skitz auth login chatgpt   connect your ChatGPT subscription (also: skitz login)
  skitz auth login claude    connect Claude with an Anthropic API key
  skitz auth logout suno     forget the saved Suno login (or: logout claude)

ChatGPT uses OAuth in your browser. Suno has no sign-in for outside apps, so Skitz
opens its own Chrome window (a separate profile under ~/.skitz): sign in to Suno
there and Skitz connects by itself, then closes the window. The session is checked
with Suno and saved privately (mode 600). Add --json for machine-readable output.
"""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import httpx

from . import browser_login, suno

SUNO_SIGN_IN = "https://suno.com/me"
SUNO_COOKIE_PAGE = f"{suno.CLERK_BASE}/v1/client"

SUNO_STEPS = f"""
Connect Suno (no Chrome found, so this is the manual way)
  1. Sign in at https://suno.com in your browser.
  2. Open {SUNO_COOKIE_PAGE}, then DevTools (Option-Cmd-I) > Application >
     Cookies > {suno.CLERK_BASE}, click the row named exactly __client and copy
     its value.
  Skitz is watching your clipboard and connects as soon as you copy it.

Waiting for the copy... (Ctrl-C to cancel)
"""


def normalize_suno_cookie(text: str) -> str:
    """Turn whatever was pasted into a `__client=...` cookie, or explain what is wrong."""
    value = text.strip().strip("'\"")
    value = re.sub(r"^cookie:\s*", "", value, flags=re.IGNORECASE)
    if not value:
        raise ValueError("Nothing was pasted.")
    if value.startswith("{") or '"response"' in value:
        # The page text holds a one-time sign-in token that Suno does not accept as a
        # session (verified October 2026), so only the cookie itself works.
        raise ValueError(
            "That is the page text, not the cookie. Copy the __client value from DevTools > "
            "Application > Cookies (and don't share that page text: it holds a token)."
        )
    match = re.search(r"(?:^|;\s*)__client=([^;\s]+)", value)
    if match:
        return f"__client={match[1]}"
    if "=" in value or ";" in value:
        names = [part.split("=", 1)[0].strip() for part in value.split(";") if "=" in part]
        raise ValueError(
            f"No __client cookie in what you pasted (found: {', '.join(names) or 'none'}). "
            f"__client only appears for {suno.CLERK_BASE}, not suno.com."
        )
    if len(value) < 20 or re.search(r"\s", value):
        raise ValueError(
            f"That doesn't look like a __client value ({len(value)} characters). "
            "It is long, with no spaces."
        )
    return f"__client={value}"


def read_clipboard() -> str:
    """The clipboard's text, or "" when no clipboard tool is available."""
    for command in (
        ["pbpaste"],
        ["wl-paste", "--no-newline"],
        ["xclip", "-o", "-selection", "clipboard"],
    ):
        if shutil.which(command[0]):
            try:
                return subprocess.run(command, capture_output=True, text=True, timeout=5).stdout
            except (OSError, subprocess.SubprocessError):
                return ""
    return ""


def suno_status(transport: httpx.BaseTransport | None = None) -> dict:
    status = {"provider": "suno", "method": "session cookie", "file": str(suno.cookie_file())}
    try:
        info = suno.SunoClient(transport=transport).billing()
    except suno.SunoError as error:
        return {**status, "connected": False, "error_kind": error.kind, "detail": error.message}
    return {**status, "connected": True, "plan": info.get("plan"), "credits": info.get("credits")}


def chatgpt_status() -> dict:
    from . import harness

    status = {"provider": "chatgpt", "method": "OAuth subscription"}
    try:
        if not harness.chatgpt_configured():
            return {**status, "connected": False}
        usable = harness.chatgpt_usable()
    except RuntimeError as error:
        return {**status, "connected": False, "detail": str(error)}
    if not usable:
        return {**status, "connected": False, "detail": "Sign-in expired."}
    return {**status, "connected": True, "model": harness.PROVIDERS["codex"]["default_model"]}


CLAUDE_MODEL_CHECK = "claude-opus-5-5"


def _check_claude_key(key: str) -> dict:
    """Confirm the key with the Anthropic API (a free model lookup); raises SunoError-free errors."""
    import anthropic

    try:
        model = anthropic.Anthropic(api_key=key, max_retries=1).models.retrieve(CLAUDE_MODEL_CHECK)
    except anthropic.AuthenticationError:
        raise ValueError("Anthropic rejected that API key.") from None
    except anthropic.PermissionDeniedError:
        raise ValueError("That API key isn't allowed to use the Anthropic API.") from None
    except anthropic.NotFoundError:
        raise ValueError(
            f"That key works, but {CLAUDE_MODEL_CHECK} isn't available to it."
        ) from None
    except anthropic.APIConnectionError as error:
        raise ValueError(f"Couldn't reach the Anthropic API: {error}") from None
    return {"model": model.id, "display_name": model.display_name}


def _save_claude_key(key: str | None) -> Path:
    """Store (or with None, remove) the key in Prime's auth.json, which the agent reads."""
    from . import harness

    path = harness.state_directory() / "auth.json"
    data = harness.read_auth()
    if key is None:
        data.pop("anthropic", None)
    else:
        data["anthropic"] = {"type": "api_key", "key": key}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.touch(mode=0o600)
    temp.chmod(0o600)
    temp.write_text(json.dumps(data, indent=2))
    temp.replace(path)
    return path


def claude_status() -> dict:
    from . import harness

    status = {"provider": "claude", "method": "Anthropic API key"}
    entry = harness.read_auth().get("anthropic") or {}
    key = (
        entry.get("key") if entry.get("type") == "api_key" else os.environ.get("ANTHROPIC_API_KEY")
    )
    if entry.get("type") == "oauth":
        return {
            **status,
            "connected": False,
            "detail": "A Claude subscription sign-in can't be used.",
        }
    if not key:
        return {**status, "connected": False}
    try:
        _check_claude_key(key)
    except ValueError as error:
        return {**status, "connected": False, "detail": str(error)}
    return {**status, "connected": True, "model": harness.PROVIDERS["claude"]["default_model"]}


def login_claude(value: str | None = None) -> dict:
    """Check an Anthropic API key and save it for the agent."""
    if value is None and not sys.stdin.isatty():
        value = sys.stdin.read()
    if value is None and os.environ.get("ANTHROPIC_API_KEY"):
        answer = input("Use the ANTHROPIC_API_KEY from your environment? [Y/n] ").strip().lower()
        if answer in {"", "y", "yes"}:
            value = os.environ["ANTHROPIC_API_KEY"]
    if value is None:
        print(
            "Connect Claude\n  Create an API key at https://platform.claude.com/settings/keys "
            "(usage is billed to that Console account),\n  then paste it below. "
            "Claude Pro/Max subscription sign-in can't be used by Skitz.\n",
            file=sys.stderr,
        )
        value = getpass.getpass("Anthropic API key (hidden): ")
    key = value.strip()
    if key.startswith("sk-ant-oat"):
        raise suno.SunoError(
            "auth_missing",
            "That's a Claude subscription token. Use an Anthropic API key (sk-ant-api...).",
        )
    if not key:
        raise suno.SunoError("auth_missing", "No API key was given.")
    try:
        model = _check_claude_key(key)
    except ValueError as error:
        raise suno.SunoError("auth_missing", str(error)) from None
    path = _save_claude_key(key)
    return {
        "status": "connected",
        "provider": "claude",
        "method": "Anthropic API key",
        "model": model["model"],
        "saved_to": str(path),
    }


def _check(raw: str, transport: httpx.BaseTransport | None) -> tuple[str, dict]:
    """Normalize a copied value and confirm it with Suno; raises ValueError or SunoError."""
    cookie = normalize_suno_cookie(raw)
    try:
        return cookie, suno.SunoClient(cookie, transport).billing()
    except suno.SunoError as error:
        if error.kind == "auth_expired":
            error.message += f" Copy __client from {suno.CLERK_BASE} while signed in."
        raise


def _connected(cookie: str, info: dict) -> dict:
    return {
        "status": "connected",
        "provider": "suno",
        "method": "session cookie",
        "plan": info.get("plan"),
        "credits": info.get("credits"),
        "saved_to": str(suno.save_cookie(cookie)),
    }


def _looks_like_suno_login(text: str) -> bool:
    return "__client" in text or '"response"' in text or bool(re.fullmatch(r"eyJ[\w.-]{20,}", text))


BROWSER_STEPS = """
Connect Suno
  A Skitz Chrome window just opened on Suno's sign-in page. Sign in there as usual.
  When you see your Suno library, come back here and press Enter
  (or quit that Chrome window with Cmd-Q).
  It is a separate Chrome profile: Skitz never reads your everyday browser.

Waiting for you to sign in... (Ctrl-C to cancel)
"""


def _login_in_skitz_browser(transport: httpx.BaseTransport | None, timeout: float) -> dict:
    def accept(header: str) -> dict | None:
        try:
            return suno.SunoClient(header, transport).billing()
        except suno.SunoError:
            return None  # signed out, or the sign-in is still finishing

    try:
        header, info = browser_login.wait_for_login(
            accept, timeout=timeout, on_waiting=lambda: print(BROWSER_STEPS, file=sys.stderr)
        )
    except (RuntimeError, TimeoutError) as error:
        raise suno.SunoError("auth_missing", str(error)) from None
    return _connected(header, info)


def login_suno(
    value: str | None = None,
    transport: httpx.BaseTransport | None = None,
    open_url: Callable[[str], object] = webbrowser.open,
    clipboard: Callable[[], str] = read_clipboard,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = 600,
    use_browser: bool = True,
) -> dict:
    """Save a working Suno login.

    With `value` (or piped stdin) it is checked directly. Otherwise Skitz opens Suno's
    login page and watches the clipboard until a copy of that page (or of the __client
    cookie) shows up, so nothing has to be pasted into the terminal.
    """
    if value is None and not sys.stdin.isatty():
        value = sys.stdin.read()
    if value is not None:
        try:
            return _connected(*_check(value, transport))
        except ValueError as error:
            raise suno.SunoError("auth_missing", str(error)) from None
        except suno.SunoError as error:
            raise suno.SunoError("auth_missing", error.message) from None

    if use_browser and browser_login.find_chrome():
        return _login_in_skitz_browser(transport, timeout)
    open_url(SUNO_COOKIE_PAGE)
    print(SUNO_STEPS, file=sys.stderr)
    deadline = time.monotonic() + timeout
    seen = None
    while time.monotonic() < deadline:
        text = clipboard().strip()
        if text and text != seen:
            seen = text
            if _looks_like_suno_login(text):
                try:
                    return _connected(*_check(text, transport))
                except (ValueError, suno.SunoError) as error:
                    print(f"  {getattr(error, 'message', error)}", file=sys.stderr)
        sleep(0.5)
    raise suno.SunoError("auth_missing", "Stopped waiting for the copy. Run the command again.")


def logout_suno() -> dict:
    path = suno.cookie_file()
    existed = path.is_file()
    if existed:
        path.unlink()
    return {"status": "logged_out" if existed else "not_logged_in", "provider": "suno"}


def show(result: dict | list, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return
    rows = result if isinstance(result, list) else [result]
    for row in rows:
        mark = "connected" if row.get("connected") or row.get("status") == "connected" else ""
        name = row.get("provider", "")
        if row.get("status") in {"logged_out", "not_logged_in"}:
            print(f"{name}: {row['status'].replace('_', ' ')}")
        elif mark:
            extra = ", ".join(
                f"{k} {row[k]}" for k in ("plan", "credits", "model") if row.get(k) is not None
            )
            print(f"{name:8} connected ({row.get('method', '')}){'  ' + extra if extra else ''}")
        else:
            hint = "" if row.get("error_kind") == "auth_missing" else row.get("detail") or ""
            print(f"{name:8} not connected  run: skitz auth login {name}  {hint}".rstrip())


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="skitz auth", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    root.add_argument("--json", action="store_true", help="Machine-readable output")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("list", help="Show every provider and whether it is connected")
    login = commands.add_parser("login", help="Connect a provider")
    login.add_argument("provider", nargs="?", choices=["suno", "chatgpt", "claude"])
    login.add_argument("--value", help="Pass the Suno cookie or Anthropic key instead of a prompt")
    logout = commands.add_parser("logout", help="Forget a saved login")
    logout.add_argument("provider", choices=["suno", "claude"])
    return root


def choose_provider(prompt: Callable[[str], str] = input) -> str:
    print("Connect which provider?\n  1) Suno     songs, stems, beat grids\n"
          "  2) ChatGPT  agent model through your subscription (default gpt-6.1-sol)\n"
          "  3) Claude   agent model through an Anthropic API key (default claude-opus-5-5)",
          file=sys.stderr)  # fmt: skip
    answer = prompt("Choose 1, 2 or 3: ").strip().lower()
    choices = {"1": "suno", "2": "chatgpt", "3": "claude"}
    return choices.get(answer, answer if answer in {"suno", "chatgpt", "claude"} else "")


def main(argv: list[str], transport: httpx.BaseTransport | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in (None, "list"):
            show([suno_status(transport), chatgpt_status(), claude_status()], args.json)
            return 0
        if args.command == "logout":
            if args.provider == "claude":
                _save_claude_key(None)
                show({"status": "logged_out", "provider": "claude"}, args.json)
            else:
                show(logout_suno(), args.json)
            return 0
        provider = args.provider or (choose_provider() if sys.stdin.isatty() else "")
        if provider == "chatgpt":
            from .harness import login

            return login()
        if provider == "claude":
            show(login_claude(args.value), args.json)
            return 0
        if provider != "suno":
            raise suno.SunoError("usage", "Name a provider: skitz auth login suno|chatgpt|claude")
        show(login_suno(args.value, transport), args.json)
        return 0
    except suno.SunoError as error:
        if args.json:
            print(json.dumps(error.report(), indent=2))
        else:
            name = "Claude" if getattr(args, "provider", None) == "claude" else "Suno"
            print(f"{name} login failed: {error.message}", file=sys.stderr)
        return error.exit_code
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 1
