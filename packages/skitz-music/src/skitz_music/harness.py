"""Product integration around the pinned Prime runtime.

Two model routes are allowed: the ChatGPT subscription (OAuth, provider openai-codex)
and Claude through an Anthropic API key (provider anthropic). Other API keys, provider
overrides and Claude subscription OAuth stay blocked.
"""

import json
import os
import shutil
import subprocess
import sys
import time
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


PROVIDERS = {
    "codex": {
        "id": "openai-codex",
        "label": "ChatGPT subscription",
        "model_env": "SKITZ_CODEX_MODEL",
        "default_model": "gpt-6.1-sol",
    },
    "claude": {
        "id": "anthropic",
        "label": "Claude (Anthropic API key)",
        "model_env": "SKITZ_CLAUDE_MODEL",
        "default_model": "claude-opus-5-5",
    },
}
PROVIDER_ALIASES = {
    "codex": "codex",
    "openai-codex": "codex",
    "chatgpt": "codex",
    "claude": "claude",
    "anthropic": "claude",
}
# Models newer than the pinned runtime's catalog, merged into its built-in providers
# through Prime's models.json. The API, endpoint and auth come from the built-in provider.
SKITZ_MODELS = {
    "openai-codex": [
        {
            "id": "gpt-6.1-sol",
            "name": "GPT-6.1 Sol",
            "reasoning": True,
            "thinkingLevelMap": {"xhigh": "xhigh", "minimal": None, "max": "max"},
            "input": ["text", "image"],
            "contextWindow": 272000,
            "maxTokens": 128000,
            # Not yet in the pinned catalog: priced like GPT-5.6 Sol for display only.
            "cost": {"input": 5, "output": 30, "cacheRead": 0.5, "cacheWrite": 6.25},
        }
    ],
    "anthropic": [
        {
            "id": "claude-opus-5-5",
            "name": "Claude Opus 5.5",
            "reasoning": True,
            "thinkingLevelMap": {"xhigh": "xhigh", "max": "max"},
            "input": ["text", "image"],
            "contextWindow": 1000000,
            "maxTokens": 128000,
            "cost": {"input": 4, "output": 20, "cacheRead": 0.2, "cacheWrite": 5},
        }
    ],
}


def state_directory(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("SKITZ_HOME", str(Path.home() / ".skitz/agent"))).expanduser().resolve()


def runtime_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    state = state_directory(env)
    for name in list(env):
        if (name.endswith("_API_KEY") and name != "ANTHROPIC_API_KEY") or name in {
            "ANTHROPIC_OAUTH_TOKEN",
            "ANTHROPIC_AUTH_TOKEN",
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


def read_auth(state: Path | None = None) -> dict:
    path = (state or state_directory()) / "auth.json"
    try:
        return json.loads(path.read_text()) if path.is_file() else {}
    except (ValueError, OSError):
        return {}


def claude_configured(auth: dict | None = None, environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    entry = (read_auth() if auth is None else auth).get("anthropic") or {}
    return entry.get("type") == "api_key" or bool(env.get("ANTHROPIC_API_KEY"))


def chatgpt_configured(auth: dict | None = None) -> bool:
    entry = (read_auth() if auth is None else auth).get("openai-codex") or {}
    return entry.get("type") == "oauth"


def _option(args: list[str], name: str) -> tuple[str | None, list[str]]:
    """Return the value of `--name value` / `--name=value` and the args without it."""
    rest, value, skip = [], None, False
    for i, arg in enumerate(args):
        if skip:
            skip = False
            continue
        if arg == name and i + 1 < len(args):
            value, skip = args[i + 1], True
        elif arg.startswith(name + "="):
            value = arg.split("=", 1)[1]
        else:
            rest.append(arg)
    return value, rest


def select_provider(
    args: list[str], environ: dict[str, str] | None = None
) -> tuple[str, list[str]]:
    """Pick codex or claude from --provider, the --model name, SKITZ_PROVIDER or sign-ins."""
    env = os.environ if environ is None else environ
    requested, rest = _option(args, "--provider")
    if requested is not None:
        if requested not in PROVIDER_ALIASES:
            raise ValueError(
                "Skitz runs on your ChatGPT subscription or Claude: use --provider codex or "
                "--provider claude. Other providers and API-key overrides are disabled"
            )
        return PROVIDER_ALIASES[requested], rest
    model, _ = _option(rest, "--model")
    if model:
        prefix = model.split("/", 1)[0] if "/" in model else None
        if prefix:
            if prefix not in PROVIDER_ALIASES:
                raise ValueError(
                    "Only ChatGPT (openai-codex/...) and Claude (anthropic/...) models"
                )
            return PROVIDER_ALIASES[prefix], rest
        return ("claude" if model.startswith("claude") else "codex"), rest
    if env.get("SKITZ_PROVIDER") in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[env["SKITZ_PROVIDER"]], rest
    auth = read_auth(state_directory(env))
    if not chatgpt_configured(auth) and claude_configured(auth, env):
        return "claude", rest
    return "codex", rest


def agent_arguments(args: list[str], environ: dict[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    for arg in args:
        if arg in {"--api-key", "--models"} or arg.startswith(("--api-key=", "--models=")):
            raise ValueError(
                "Skitz signs in with skitz auth login (ChatGPT subscription or Anthropic API "
                "key); --api-key and --models overrides are disabled"
            )
    provider, rest = select_provider(args, env)
    spec = PROVIDERS[provider]
    model, rest = _option(rest, "--model")
    if model and "/" in model:
        model = model.split("/", 1)[1]
    if not model:
        legacy = env.get("SKITZ_MODEL") if provider == "codex" else None
        model = env.get(spec["model_env"]) or legacy or spec["default_model"]
    root = repository()
    return [
        "--provider",
        spec["id"],
        "--model",
        model,
        "--no-skills",
        "--skill",
        str(root / "packages/skitz-music"),
        "--append-system-prompt",
        str(root / "apps/cli/music-prompt.md"),
        *rest,
    ]


def ensure_models_file(state: Path | None = None) -> Path:
    """Merge Skitz's model additions into Prime's models.json, keeping user entries."""
    path = (state or state_directory()) / "models.json"
    data = json.loads(path.read_text()) if path.is_file() else {}
    providers = data.setdefault("providers", {})
    for provider_id, models in SKITZ_MODELS.items():
        entry = providers.setdefault(provider_id, {})
        existing = {m.get("id"): m for m in entry.get("models", [])}
        for model in models:
            existing.setdefault(model["id"], model)
        entry["models"] = list(existing.values())
    text = json.dumps(data, indent=2) + "\n"
    if not path.is_file() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return path


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
    provider = "claude" if prepared[1] == "anthropic" else "codex"
    informational = any(arg in {"--help", "-h", "--version", "-v"} for arg in args)
    ensure_models_file()
    if not informational and provider == "claude" and not claude_configured():
        raise RuntimeError(
            "Connect Claude with an Anthropic API key first: skitz auth login claude"
        )
    if not informational and provider == "codex" and not chatgpt_usable():
        if headless(args):
            raise RuntimeError(
                "Your ChatGPT sign-in is missing or expired. Sign in again: skitz login"
            )
        print("Your ChatGPT sign-in is missing or expired. Opening sign-in...", file=sys.stderr)
        if login() != 0:
            return 1
    return subprocess.call([*node_command(script), *prepared], env=runtime_environment())


def chatgpt_usable() -> bool:
    """Ask Prime's auth storage for a working ChatGPT credential (refreshing it if needed)."""
    if not chatgpt_configured():
        return False
    try:
        result = subprocess.run(
            [*node_command(repository() / "apps/cli/login.ts"), "--check"],
            env=runtime_environment(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return bool(json.loads(result.stdout.strip().splitlines()[-1]).get("usable"))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return False


def login(status: bool = False) -> int:
    command = node_command(repository() / "apps/cli/login.ts")
    return subprocess.call([*command, *(["--status"] if status else [])], env=runtime_environment())


def doctor() -> dict:
    env = runtime_environment()
    state = Path(env["PRIME_AGENT_CODING_AGENT_DIR"])
    auth = read_auth(state)
    codex = auth.get("openai-codex") or {}
    expires = codex.get("expires")
    return {
        "state_directory": str(state),
        "subscription_configured": chatgpt_configured(auth),
        "chatgpt_access_expired": isinstance(expires, int | float) and expires / 1000 < time.time(),
        "claude_configured": claude_configured(auth),
        "providers": {
            name: {"provider": spec["id"], "default_model": spec["default_model"]}
            for name, spec in PROVIDERS.items()
        },
        "api_key_fallback": False,
        "tools": {
            name: shutil.which(name)
            for name in ("node", "uv", "lilypond", "fluidsynth", "sandbox-exec")
        },
        "runtime_installed": (repository() / "vendor/prime-agent/node_modules/tsx").is_dir(),
    }
