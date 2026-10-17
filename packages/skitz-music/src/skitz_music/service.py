"""Workspace-confined operations used by the CLI and MCP interface."""

import json
import zipfile
from pathlib import Path

from .analysis import analyze_voice_leading, compare_revisions, inspect_score, validate_score
from .patch import PatchEdit
from .render import render_score
from .score import Score
from .store import Project


class MusicService:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def path(self, relative: str) -> Path:
        result = (self.workspace / relative).resolve()
        if not result.is_relative_to(self.workspace):
            raise ValueError("Path escapes the music workspace")
        return result

    def project(self, relative: str) -> Project:
        project = Project(self.path(relative))
        if project.state.exists():
            for path in [project.state, *project.state.rglob("*")]:
                if path.is_symlink():
                    raise ValueError("Project state cannot contain symbolic links")
        return project

    def create_project(self, project: str, score: Score, protected_tracks: list[str]) -> dict:
        return self.project(project).create(Score.model_validate(score), protected_tracks)

    def inspect_score(self, project: str, revision: str | None = None) -> dict:
        return inspect_score(self.project(project).read(revision))

    def validate_score(self, project: str, revision: str | None = None) -> dict:
        return validate_score(self.project(project).read(revision))

    def analyze_voice_leading(self, project: str, revision: str | None = None) -> dict:
        return analyze_voice_leading(self.project(project).read(revision))

    def apply_score_patch(
        self,
        project: str,
        expected_revision: str,
        edits: list[PatchEdit],
        allowed_measures: list[int],
        reason: str,
    ) -> dict:
        return self.project(project).apply_score_patch(
            expected_revision, edits, allowed_measures, reason
        )

    def compare_revisions(self, project: str, before: str, after: str) -> dict:
        store = self.project(project)
        return compare_revisions(store.read(before), store.read(after))

    def render_score(
        self,
        project: str,
        revision: str | None = None,
        soundfont: str | None = None,
        audio: bool = True,
        engrave: bool = True,
    ) -> dict:
        store = self.project(project)
        sf = str(self.path(soundfont)) if soundfont else None
        return render_score(
            store.read(revision), self.path(str(Path(project) / "renders")), sf, audio, engrave
        )

    def rollback(self, project: str, expected_revision: str, target_revision: str) -> dict:
        return self.project(project).rollback(expected_revision, target_revision)

    def export_project(self, project: str, destination: str) -> dict:
        store = self.project(project)
        score = store.read()
        target = self.path(destination)
        if target.is_relative_to(store.state) or target.is_relative_to(store.path / "renders"):
            raise ValueError("Export destination must be outside project state and renders")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("score.json", json.dumps(score.model_dump(mode="json"), indent=2))
            for path in sorted(store.state.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.name != "lock":
                    archive.write(path, str(path.relative_to(store.path)))
            renders = self.path(str(Path(project) / "renders"))
            if renders.is_dir():
                for manifest_file in sorted(renders.rglob("manifest.json")):
                    if manifest_file.is_symlink() or not manifest_file.resolve().is_relative_to(
                        self.workspace
                    ):
                        continue
                    manifest = json.loads(manifest_file.read_text())
                    if manifest["revision"] != score.revision:
                        continue
                    for path in sorted(manifest_file.parent.iterdir()):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, str(path.relative_to(store.path)))
        return {"revision": score.revision, "path": str(target), "status": "exported"}
