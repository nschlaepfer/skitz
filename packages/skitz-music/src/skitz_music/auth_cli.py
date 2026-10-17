"""`skitz auth ...`: sign in to the services Skitz uses, one command per provider.

  skitz auth                 show every provider and whether it is connected
  skitz auth login           pick a provider from a menu
  skitz auth login suno      connect your Suno account (also: skitz login suno)
  skitz auth login chatgpt   connect your ChatGPT subscription (also: skitz login)
  skitz auth logout suno     forget the saved Suno login

ChatGPT uses OAuth in your browser. Suno has no sign-in for outside apps, so Skitz
opens the right page and asks you to paste one cookie value, which it checks with
Suno before saving it privately (mode 600). Add --json for machine-readable output.
"""

import argparse
import getpass
import json
import re
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable

import httpx

from . import suno

SUNO_SIGN_IN = "https://suno.com/me"
SUNO_COOKIE_PAGE = f"{suno.CLERK_BASE}/v1/client"

SUNO_STEPS = f"""
Connect Suno
  1. Sign in at {SUNO_SIGN_IN} (opening it now).
  2. Open {SUNO_COOKIE_PAGE} in Chrome (opening it next).
     It shows a page of text; leave it.
  3. On that tab open DevTools (Option-Cmd-I) > Application > Cookies >
     {suno.CLERK_BASE}, click the row named exactly __client, and copy its value.
  4. Come back here and press Enter: Skitz reads the value from your clipboard.
     (It is too long to paste into a terminal prompt on macOS.)
"""


def normalize_suno_cookie(text: str) -> str:
    """Turn whatever was pasted into a `__client=...` cookie, or explain what is wrong."""
    value = text.strip().strip("'\"")
    value = re.sub(r"^cookie:\s*", "", value, flags=re.IGNORECASE)
    if not value:
        raise ValueError("Nothing was pasted.")
    if value.startswith("{") or '"response"' in value:
        raise ValueError(
            "That is the page text, not the cookie. Copy the __client value from DevTools > "
            "Application > Cookies instead (and don't share that page text: it holds a token)."
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
    from .harness import doctor

    try:
        connected = doctor()["subscription_configured"]
    except RuntimeError as error:
        return {"provider": "chatgpt", "method": "OAuth", "connected": False, "detail": str(error)}
    return {"provider": "chatgpt", "method": "OAuth", "connected": connected}


def login_suno(
    value: str | None = None,
    transport: httpx.BaseTransport | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
    open_url: Callable[[str], object] = webbrowser.open,
    clipboard: Callable[[], str] = read_clipboard,
    attempts: int = 3,
) -> dict:
    """Save a working Suno login. With `value`, no prompts; otherwise guide the user."""
    if value is None and not sys.stdin.isatty():
        value = sys.stdin.read()
    interactive = value is None
    if interactive:
        print(SUNO_STEPS, file=sys.stderr)
        open_url(SUNO_SIGN_IN)
        prompt("Press Enter once you are signed in to Suno... ")
        open_url(SUNO_COOKIE_PAGE)
    for attempt in range(1, attempts + 1):
        if interactive:
            # Terminals cap a typed line at 1024 bytes, shorter than the cookie, so a
            # pasted value is silently cut off; pressing Enter reads the clipboard instead.
            typed = prompt("Copy the __client value, then press Enter here: ")
            raw = typed if typed.strip() else clipboard()
        else:
            raw = value
        try:
            cookie = normalize_suno_cookie(raw or "")
            info = suno.SunoClient(cookie, transport).billing()
        except ValueError as error:
            problem = str(error)
        except suno.SunoError as error:
            problem = error.message
            if error.kind == "auth_expired":
                problem += (
                    f" Check that you copied __client from {suno.CLERK_BASE} while signed in."
                )
        else:
            path = suno.save_cookie(cookie)
            return {
                "status": "connected",
                "provider": "suno",
                "plan": info.get("plan"),
                "credits": info.get("credits"),
                "saved_to": str(path),
            }
        if not interactive or attempt == attempts:
            raise suno.SunoError("auth_missing", problem)
        print(f"  {problem} Try again ({attempts - attempt} left).", file=sys.stderr)
    raise AssertionError("unreachable")


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
                f"{k} {row[k]}" for k in ("plan", "credits") if row.get(k) is not None
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
    login.add_argument("provider", nargs="?", choices=["suno", "chatgpt"])
    login.add_argument("--value", help="Suno: pass the cookie instead of being prompted")
    logout = commands.add_parser("logout", help="Forget a saved login")
    logout.add_argument("provider", choices=["suno"])
    return root


def choose_provider(prompt: Callable[[str], str] = input) -> str:
    print("Connect which provider?\n  1) Suno     songs, stems, beat grids\n"
          "  2) ChatGPT  the Skitz agent's model (subscription)", file=sys.stderr)  # fmt: skip
    answer = prompt("Choose 1 or 2: ").strip().lower()
    return {"1": "suno", "suno": "suno", "2": "chatgpt", "chatgpt": "chatgpt"}.get(answer, "")


def main(argv: list[str], transport: httpx.BaseTransport | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in (None, "list"):
            show([suno_status(transport), chatgpt_status()], args.json)
            return 0
        if args.command == "logout":
            show(logout_suno(), args.json)
            return 0
        provider = args.provider or (choose_provider() if sys.stdin.isatty() else "")
        if provider == "chatgpt":
            from .harness import login

            return login()
        if provider != "suno":
            raise suno.SunoError("usage", "Name a provider: skitz auth login suno|chatgpt")
        show(login_suno(args.value, transport), args.json)
        return 0
    except suno.SunoError as error:
        if args.json:
            print(json.dumps(error.report(), indent=2))
        else:
            print(f"Suno login failed: {error.message}", file=sys.stderr)
        return error.exit_code
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 1
