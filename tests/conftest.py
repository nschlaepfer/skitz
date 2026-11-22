import pytest


@pytest.fixture(autouse=True)
def hermetic_suno_state(tmp_path, monkeypatch):
    """Keep Suno's jobs, spend ledger, budget, inbox and Chrome profile in a temp dir,
    and ignore any budget or profile set in the developer's shell."""
    monkeypatch.setenv("SKITZ_SUNO_HOME", str(tmp_path / "suno-home"))
    monkeypatch.setenv("SKITZ_SUNO_WATCH", str(tmp_path / "Downloads"))
    for name in ("SKITZ_SUNO_BUDGET", "SKITZ_SUNO_BROWSER_PROFILE", "SKITZ_SUNO_INBOX"):
        monkeypatch.delenv(name, raising=False)
