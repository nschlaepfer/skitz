import subprocess
import sys

import pytest
from skitz_music import harness


def test_existing_state_overrides_survive_branding(tmp_path):
    env = harness.runtime_environment({"SKITZ_HOME": str(tmp_path)})
    assert env["SKITZ_PRODUCT"] == "1"
    assert env["PRIME_AGENT_CODING_AGENT_DIR"] == str(tmp_path)
    assert env["PRIME_AGENT_SESSION_DIR"] == str(tmp_path / "sessions")


def test_headless_missing_login_has_no_upstream_onboarding(monkeypatch):
    monkeypatch.setattr(harness, "doctor", lambda: {"subscription_configured": False})
    # The launcher asks whether the ChatGPT sign-in works; keep the test independent of
    # the machine's real sign-in.
    monkeypatch.setattr(harness, "chatgpt_usable", lambda: False)
    monkeypatch.setenv("SKITZ_PROVIDER", "codex")
    with pytest.raises(RuntimeError, match="skitz login"):
        harness.launch_agent(["-p", "compose a phrase"])


@pytest.mark.parametrize("args", [["--help"], ["agent", "--help"]])
def test_actual_agent_help_is_music_specific(args):
    result = subprocess.run(
        [sys.executable, "-m", "skitz_music.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "ChatGPT subscription" in output
    assert "Prime" not in output
    assert "--api-key" not in output
