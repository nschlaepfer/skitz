import pytest
from skitz_music.harness import agent_arguments, runtime_environment


def test_subscription_launcher_removes_api_keys_and_isolates_state(tmp_path):
    env = runtime_environment(
        {
            "SKITZ_HOME": str(tmp_path),
            "OPENAI_API_KEY": "test-not-a-key",
            "PRIME_AGENT_CODING_AGENT_DIR": "/other",
            "PRIME_AGENT_KERNEL_PYTHON": "/other/python",
        }
    )
    assert "OPENAI_API_KEY" not in env
    assert "PRIME_AGENT_KERNEL_PYTHON" not in env
    assert env["PRIME_AGENT_CODING_AGENT_DIR"] == str(tmp_path)
    assert env["PRIME_AGENT_KERNEL_VENV"] == str(tmp_path / "kernel-venv")
    assert env["SKITZ_DISABLE_UPDATES"] == "1"
    assert agent_arguments([])[:2] == ["--provider", "openai-codex"]


@pytest.mark.parametrize(
    "args",
    [
        ["--api-key", "test"],
        ["--provider", "openai"],
        ["--model", "openai/gpt-5.5"],
        ["--models", "*"],
    ],
)
def test_no_api_key_override(args):
    with pytest.raises(ValueError):
        agent_arguments(args)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], False),
        (["--mode", "text"], False),
        (["--mode=text"], False),
        (["--mode", "json"], True),
        (["--mode=rpc"], True),
        (["-p", "hello"], True),
    ],
)
def test_only_headless_modes_skip_interactive_sign_in(args, expected, monkeypatch):
    import sys

    from skitz_music.harness import headless

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert headless(args) is expected


# Built at runtime so no key-shaped literal sits in the repository for secret scanners.
FAKE_API_KEY = "-".join(["sk", "ant", "api03", "placeholder"])
FAKE_OAUTH_TOKEN = "-".join(["sk", "ant", "oat01", "placeholder"])


def _home(tmp_path, auth=None):
    import json

    if auth is not None:
        (tmp_path / "auth.json").write_text(json.dumps(auth))
    return {"SKITZ_HOME": str(tmp_path)}


def test_defaults_are_gpt_6_1_sol_and_claude_opus_5_5(tmp_path):
    env = _home(tmp_path, {"openai-codex": {"type": "oauth"}})
    assert agent_arguments([], env)[:4] == ["--provider", "openai-codex", "--model", "gpt-6.1-sol"]
    claude = agent_arguments(["--provider", "claude"], env)
    assert claude[:4] == ["--provider", "anthropic", "--model", "claude-opus-5-5"]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--model", "claude-sonnet-5-5"], ["anthropic", "claude-sonnet-5-5"]),
        (["--model", "anthropic/claude-opus-5"], ["anthropic", "claude-opus-5"]),
        (["--model=openai-codex/gpt-6-astra"], ["openai-codex", "gpt-6-astra"]),
        (["--provider=codex", "--model", "gpt-5.6-sol"], ["openai-codex", "gpt-5.6-sol"]),
    ],
)
def test_model_names_pick_the_provider(tmp_path, args, expected):
    out = agent_arguments(args, _home(tmp_path))
    assert [out[1], out[3]] == expected
    assert "--provider" not in out[2:] and out.count("--model") == 1


def test_auto_picks_claude_when_only_claude_is_connected(tmp_path):
    env = _home(tmp_path, {"anthropic": {"type": "api_key", "key": FAKE_API_KEY}})
    assert agent_arguments([], env)[1] == "anthropic"
    env["SKITZ_PROVIDER"] = "codex"
    assert agent_arguments([], env)[1] == "openai-codex"
    assert (
        agent_arguments([], {**env, "SKITZ_PROVIDER": "claude", "SKITZ_CLAUDE_MODEL": "x"})[3]
        == "x"
    )


def test_only_the_anthropic_key_reaches_the_runtime(tmp_path):
    env = runtime_environment(
        {
            "SKITZ_HOME": str(tmp_path),
            "ANTHROPIC_API_KEY": FAKE_API_KEY,
            "OPENAI_API_KEY": "test-not-a-key",
            "ANTHROPIC_AUTH_TOKEN": "test-token",
            "ANTHROPIC_OAUTH_TOKEN": FAKE_OAUTH_TOKEN,
        }
    )
    assert env["ANTHROPIC_API_KEY"] == FAKE_API_KEY
    assert not {"OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_OAUTH_TOKEN"} & set(env)


def test_models_file_adds_new_models_and_keeps_user_entries(tmp_path):
    import json

    from skitz_music.harness import ensure_models_file

    (tmp_path / "models.json").write_text(
        json.dumps({"providers": {"ollama": {"baseUrl": "http://x", "models": [{"id": "llama"}]}}})
    )
    path = ensure_models_file(tmp_path)
    data = json.loads(path.read_text())
    assert data["providers"]["ollama"]["models"] == [{"id": "llama"}]
    ids = {p: [m["id"] for m in v["models"]] for p, v in data["providers"].items()}
    assert ids["openai-codex"] == ["gpt-6.1-sol"] and ids["anthropic"] == ["claude-opus-5-5"]
    opus = data["providers"]["anthropic"]["models"][0]
    assert opus["contextWindow"] == 1_000_000 and opus["maxTokens"] == 128_000
    before = path.read_text()
    ensure_models_file(tmp_path)
    assert path.read_text() == before  # idempotent
