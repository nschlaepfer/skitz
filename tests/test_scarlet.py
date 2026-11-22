import argparse
import json

import pytest
from skitz_music import scarlet


@pytest.fixture
def parse():
    parser = argparse.ArgumentParser()
    scarlet.add_command(parser)
    return parser.parse_args


def test_headless_registration_passes_token_file_path(parse, tmp_path, monkeypatch):
    cli = tmp_path / "packages/mcp/dist/cli.js"
    cli.parent.mkdir(parents=True)
    cli.touch()
    token_file = tmp_path / "access-token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    calls = []
    monkeypatch.setenv("SKITZ_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(scarlet, "run_prime", lambda command: calls.append(command) or 0)
    monkeypatch.setattr(scarlet.shutil, "which", lambda _: "/usr/bin/node")
    flags = ["connect", "--checkout", str(tmp_path), "--project", "prj_test",
             "--token-file", str(token_file), "--force"]

    assert scarlet.run(parse(flags)) == 0
    assert calls[0][:5] == ["mcp", "add", "scarlet", "--force", "--"]
    assert "--headless" in calls[0]
    assert f"--workdir={tmp_path / 'state/scarlet-artifacts/prj_test'}" in calls[0]
    assert f"--token-file={token_file}" in calls[0]
    assert "fixture-token" not in " ".join(calls[0])
    with pytest.raises(ValueError, match="HTTPS or loopback"):
        scarlet.run(parse([*flags, "--server", "http://public.example.com"]))
    assert len(calls) == 1


def test_desktop_session_uses_latest_loopback_port(parse, tmp_path, monkeypatch, capsys):
    session = tmp_path / "desktop-session.json"
    token = "sct_" + "a" * 64
    session.touch(mode=0o600)
    seen = []

    def list_projects(server, credential):
        seen.append((server, credential))
        return [{"id": "prj_example", "name": "Example"}]

    monkeypatch.setattr(scarlet, "_projects", list_projects)
    for port in (4040, 5050):
        session.write_text(json.dumps({"port": port, "token": token}))
        assert scarlet.run(parse(["projects", "--desktop-data", str(tmp_path)])) == 0
        assert json.loads(capsys.readouterr().out) == [{"id": "prj_example", "name": "Example"}]
    assert seen == [("http://127.0.0.1:4040", token), ("http://127.0.0.1:5050", token)]


def test_stage_audio_is_project_scoped_and_content_addressed(parse, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SKITZ_HOME", str(tmp_path / "state"))
    source = tmp_path / "My mix.WAV"
    source.write_bytes(b"sample")

    def stage(project):
        assert scarlet.run(parse(["stage-audio", str(source), "--project", project])) == 0
        return json.loads(capsys.readouterr().out)["path"]

    name = stage("prj_first")
    assert name.startswith("My-mix-") and name.endswith(".wav")
    assert stage("prj_first") == name
    artifact = tmp_path / "state/scarlet-artifacts/prj_first" / name
    assert list(artifact.parent.iterdir()) == [artifact]
    assert artifact.read_bytes() == source.read_bytes()
    assert stage("prj_second") == name
    source.write_bytes(b"alternate mix")
    assert stage("prj_first") != name
    assert artifact.read_bytes() == b"sample"
    with pytest.raises(ValueError, match="project ID"):
        stage("../prj_first")
