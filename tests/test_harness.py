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
