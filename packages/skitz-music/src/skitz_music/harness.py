"""Product integration around the pinned Prime runtime; subscription auth only."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def repository() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "vendor/prime-agent/prime-agent.sh").is_file():
            return parent
    override = os.environ.get("SKITZ_REPO")
    if override and (Path(override) / "vendor/prime-agent/prime-agent.sh").is_file():
        return Path(override).resolve()
    raise RuntimeError(
        "Skitz currently runs from its source checkout; set SKITZ_REPO to that checkout"
    )


def runtime_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    state = Path(env.get("SKITZ_HOME", str(Path.home() / ".skitz/agent"))).expanduser().resolve()
    for name in list(env):
        if name.endswith("_API_KEY") or name in {
            "ANTHROPIC_OAUTH_TOKEN",
            "PRIME_AGENT_KERNEL_PYTHON",
            "PI_PACKAGE_DIR",
            "PRIME_AGENT_SESSION_DIR",
            "PRIME_AGENT_CODING_AGENT_SESSION_DIR",
            "PI_CODING_AGENT_DIR",
            "PI_SESSION_DIR",
            "PI_CODING_AGENT_SESSION_DIR",
        }:
            env.pop(name, None)
    env.update(
        {
            "PRIME_AGENT_CODING_AGENT_DIR": str(state),
            "PRIME_AGENT_SESSION_DIR": str(state / "sessions"),
            "PRIME_AGENT_KERNEL_VENV": str(state / "kernel-venv"),
            "SKITZ_SUBSCRIPTION_ONLY": "1",
            "SKITZ_PRODUCT": "1",
            "SKITZ_DISABLE_UPDATES": "1",
            "PI_OFFLINE": "1",
        }
    )
    return env


def node_command(script: Path) -> list[str]:
    prime = repository() / "vendor/prime-agent"
    tsx = prime / "node_modules/tsx/dist/cli.mjs"
    if not tsx.is_file():
        raise RuntimeError("Install the pinned runtime: npm ci --prefix vendor/prime-agent")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 22.8 or newer is required")
    return [node, str(tsx), "--tsconfig", str(prime / "tsconfig.json"), str(script)]


def agent_arguments(args: list[str]) -> list[str]:
    for i, arg in enumerate(args):
        if arg in {"--api-key", "--provider", "--models"} or arg.startswith(
            ("--api-key=", "--provider=", "--models=")
        ):
            raise ValueError(
                "Skitz uses ChatGPT subscription sign-in. Use skitz login; API-key/provider overrides are disabled"
            )
        if arg == "--model" and i + 1 < len(args) and "/" in args[i + 1]:
            if not args[i + 1].startswith("openai-codex/"):
                raise ValueError("Only openai-codex subscription models are enabled")
    root = repository()
    defaults = ["--provider", "openai-codex"]
    if "--model" not in args:
        defaults += ["--model", os.environ.get("SKITZ_MODEL", "gpt-5.5")]
    return [
        *defaults,
        "--no-skills",
        "--skill",
        str(root / "packages/skitz-music"),
        "--append-system-prompt",
        str(root / "apps/cli/music-prompt.md"),
        *args,
    ]


HEADLESS_MODES = {"json", "rpc", "acp", "daemon"}


def headless(args: list[str]) -> bool:
    """True when the agent cannot run an interactive sign-in (print or non-text modes)."""
    if "-p" in args or "--print" in args or not sys.stdin.isatty():
        return True
    for i, arg in enumerate(args):
        if arg.startswith("--mode="):
            return arg.split("=", 1)[1] in HEADLESS_MODES
        if arg == "--mode" and i + 1 < len(args):
            return args[i + 1] in HEADLESS_MODES
    return False


def launch_agent(args: list[str]) -> int:
    if args and args[0] in {"update", "/update"}:
        raise ValueError("Skitz pins its Prime runtime; update it through a reviewed source import")
    script = repository() / "vendor/prime-agent/packages/coding-agent/src/cli.ts"
    prepared = agent_arguments(args)
    informational = any(arg in {"--help", "-h", "--version", "-v"} for arg in args)
    if not informational and not doctor()["subscription_configured"]:
        if headless(args):
            raise RuntimeError("Sign in with your ChatGPT subscription first: skitz login")
        if login() != 0:
            return 1
    return subprocess.call([*node_command(script), *prepared], env=runtime_environment())


def login(status: bool = False) -> int:
    command = node_command(repository() / "apps/cli/login.ts")
    return subprocess.call([*command, *(["--status"] if status else [])], env=runtime_environment())


def doctor() -> dict:
    env = runtime_environment()
    state = Path(env["PRIME_AGENT_CODING_AGENT_DIR"])
    auth = state / "auth.json"
    signed_in = False
    if auth.is_file():
        try:
            signed_in = json.loads(auth.read_text()).get("openai-codex", {}).get("type") == "oauth"
        except (ValueError, OSError):
            pass
    return {
        "state_directory": str(state),
        "subscription_configured": signed_in,
        "provider": "openai-codex",
        "api_key_fallback": False,
        "tools": {
            name: shutil.which(name)
            for name in ("node", "uv", "lilypond", "fluidsynth", "sandbox-exec")
        },
        "runtime_installed": (repository() / "vendor/prime-agent/node_modules/tsx").is_dir(),
    }
