"""Register Scarlet's project-scoped stdio MCP server with Skitz's Prime runtime."""

import argparse
import http.client
import ipaddress
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .harness import run_prime


def add_command(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="scarlet_command", required=True)
    connect = commands.add_parser("connect", help="Register an existing Scarlet project")
    install = connect.add_mutually_exclusive_group(required=True)
    install.add_argument("--checkout", type=Path, help="Path to a built Scarlet source checkout")
    install.add_argument("--engine", type=Path, help="Path to a Scarlet engine executable")
    projects = commands.add_parser("projects", help="List project names and IDs on an engine")
    for command in (connect, projects):
        endpoint = command.add_mutually_exclusive_group()
        endpoint.add_argument("--server", help="Headless engine URL (default http://127.0.0.1:4000)")
        endpoint.add_argument("--desktop-data", type=Path, help="Scarlet desktop's data directory")
        command.add_argument("--token-file", type=Path, help="Headless engine's access token file")
    connect.add_argument("--project", required=True, help="Scarlet project ID")
    connect.add_argument("--force", action="store_true", help="Replace the existing registration")
    commands.add_parser("status", help="Show whether Scarlet is registered")
    commands.add_parser("disconnect", help="Remove the Scarlet registration from Skitz")


def _validate_server(address: str) -> None:
    message = "Use an HTTPS or loopback HTTP Scarlet URL without credentials, query, or fragment"
    if any(char.isspace() for char in address) or any(char in address for char in "\\?#"):
        raise ValueError(message)
    url = urlsplit(address)
    host = url.hostname
    if not host or url.username is not None or url.password is not None:
        raise ValueError(message)
    # Accessing the parsed port rejects malformed and out-of-range ports.
    _ = url.port
    if url.scheme == "https":
        return
    if url.scheme == "http":
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
    raise ValueError(message)


def run(args: argparse.Namespace) -> int:
    if args.scarlet_command in {"status", "disconnect"}:
        action = "get" if args.scarlet_command == "status" else "remove"
        return run_prime(["mcp", action, "scarlet"])

    if args.desktop_data:
        if args.token_file:
            raise ValueError("--desktop-data uses the running desktop session's credential")
        data = args.desktop_data.expanduser().resolve()
        if not data.is_dir():
            raise ValueError("Provide Scarlet's desktop data directory")
    else:
        server = args.server or "http://127.0.0.1:4000"
        _validate_server(server)
        if not args.token_file:
            raise ValueError("Provide the headless engine's --token-file")
        token_file = args.token_file.expanduser().absolute()
        _check_private_file(token_file.lstat())

    if args.scarlet_command == "projects":
        if args.desktop_data:
            server, token = _desktop_session(data)
        else:
            token = _read_private_file(token_file).decode().strip()
        print(json.dumps(_projects(server, token), indent=2))
        return 0

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.project):
        raise ValueError("Provide a Scarlet project ID (letters, numbers, underscores or hyphens)")
    if args.checkout:
        cli = args.checkout.expanduser().resolve() / "packages/mcp/dist/cli.js"
        if not cli.is_file():
            raise ValueError("Build Scarlet first: pnpm --filter @scarlet/mcp... build")
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js 22.8 or newer is required")
        command = [node, str(cli)]
    else:
        binary = args.engine.expanduser().resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError("Provide the path to an executable Scarlet engine")
        command = [str(binary), "mcp"]

    command.extend([f"--project={args.project}", "--agent=skitz"])
    if args.desktop_data:
        command = [sys.executable, "-I", "-m", __name__, str(data), *command]
    else:
        command.extend([f"--server={server}", f"--token-file={token_file}"])

    replace = ["--force"] if args.force else []
    return run_prime(["mcp", "add", "scarlet", *replace, "--", *command])


def _check_private_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or (
        os.name != "nt" and (info.st_mode & 0o077 or info.st_uid != os.getuid())
    ):
        raise ValueError("Use a regular Scarlet credential file accessible only to its owner")


def _read_private_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as file:
        info = os.fstat(file.fileno())
        _check_private_file(info)
        if not 0 < info.st_size <= 4096:
            raise ValueError("Invalid Scarlet credential file")
        return file.read(4096)


def _desktop_session(data: Path) -> tuple[str, str]:
    # The rotating credential is valid only for this desktop engine session.
    try:
        payload = json.loads(_read_private_file(data / "desktop-session.json"))
        port, token = payload["port"], payload["token"]
        if type(port) is not int or not 0 < port <= 65535:
            raise ValueError
        if not isinstance(token, str) or not re.fullmatch(r"sct_[a-f0-9]{64}", token):
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError("Open Scarlet and check that the desktop data directory is correct") from None
    return f"http://127.0.0.1:{port}", token


def _projects(server: str, token: str) -> list[dict[str, str]]:
    url = urlsplit(server)
    transport = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = transport(url.hostname, url.port, timeout=10)
    try:
        connection.request(
            "GET", f"{url.path.rstrip('/')}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Scarlet could not list projects (HTTP {response.status})")
        return [{"id": p["id"], "name": p["name"]} for p in json.load(response)["projects"]]
    except (http.client.HTTPException, ValueError, TypeError, KeyError):
        raise RuntimeError("Scarlet returned an invalid project listing") from None
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        server, token = _desktop_session(Path(sys.argv[1]))
        program, *command = sys.argv[2:]
        os.execve(program, [program, *command, f"--server={server}"], {
            **os.environ, "SCARLET_TOKEN": token,
        })
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
