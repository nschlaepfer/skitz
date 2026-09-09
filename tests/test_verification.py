import json
import zipfile
from pathlib import Path

import pytest
from skitz_music import Project
from skitz_music.fixtures import chorale_fixture
from skitz_music.render import render_score
from skitz_music.service import MusicService
from skitz_music.verification import verify_project


def test_missing_artifacts_never_pass_verification(tmp_path):
    Project(tmp_path).create(chorale_fixture(), ["soprano"])
    assert verify_project(tmp_path)["status"] == "failed"


def test_export_retains_nested_renders_and_history(tmp_path):
    project = Project(tmp_path / "piece")
    project.create(chorale_fixture(), ["soprano"])
    manifest = render_score(
        project.read(), project.path / "renders/final", audio=False, engrave=False
    )
    service = MusicService(tmp_path)
    service.export_project("piece", "accepted.zip")
    with zipfile.ZipFile(tmp_path / "accepted.zip") as archive:
        assert "score.json" in archive.namelist()
        assert ".skitz/history.jsonl" in archive.namelist()
        assert any(name.endswith("manifest.json") for name in archive.namelist())
    file = Path(manifest["output_directory"]) / "score.json"
    assert json.loads(file.read_text())["title"] == chorale_fixture().title


def test_service_rejects_internal_state_symlink(tmp_path):
    outside = tmp_path / "outside"
    Project(outside).create(chorale_fixture())
    workspace = tmp_path / "workspace"
    (workspace / "piece").mkdir(parents=True)
    (workspace / "piece/.skitz").symlink_to(outside / ".skitz", target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        MusicService(workspace).inspect_score("piece")
