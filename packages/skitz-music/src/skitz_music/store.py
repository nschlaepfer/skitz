"""Immutable score revisions with optimistic concurrency and persistent edit constraints."""

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .analysis import changed_measures, compare_revisions, validate_score
from .patch import apply_edits
from .score import SCHEMA_VERSION, Score, canonical_json


def atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Project:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.state = self.path / ".skitz"

    @contextmanager
    def locked(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def create(self, score: Score, protected_tracks: list[str] | None = None) -> dict:
        protected = protected_tracks or []
        if not set(protected) <= {t.id for t in score.tracks}:
            raise ValueError("Unknown protected track")
        self._valid(score)
        with self.locked():
            if (self.state / "HEAD.json").exists():
                raise ValueError("Project already exists")
            atomic_json(self.state / "format.json", {"schema_version": SCHEMA_VERSION})
            atomic_json(
                self.state / "policy.json",
                {"protected_tracks": protected, "baseline": score.revision},
            )
            self._save(score, parent=None, reason="create")
        return {"revision": score.revision, "status": "created", "protected_tracks": protected}

    def read(self, revision: str | None = None) -> Score:
        self.migrate()
        return self._read(revision)

    def _read(self, revision: str | None = None) -> Score:
        revision = revision or json.loads((self.state / "HEAD.json").read_text())["revision"]
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("Invalid revision")
        revision = self._aliases().get(revision, revision)
        score = Score.model_validate_json(
            (self.state / "revisions" / f"{revision}.json").read_text()
        )
        if score.revision != revision:
            raise ValueError("Revision integrity check failed")
        return score

    def _aliases(self) -> dict[str, str]:
        """Schema-1 revision IDs mapped to the IDs of their migrated schema-2 revisions."""
        file = self.state / "migrations.json"
        return json.loads(file.read_text())["revisions"] if file.is_file() else {}

    def _current(self) -> bool:
        marker = self.state / "format.json"
        if marker.is_file():
            version = json.loads(marker.read_text()).get("schema_version")
            if version > SCHEMA_VERSION:
                raise ValueError(f"Project uses score schema {version}; update Skitz to open it")
            return version == SCHEMA_VERSION
        return not (self.state / "HEAD.json").exists()

    def migrate(self) -> dict:
        """Upgrade a schema-1 project in place. Original revisions stay as evidence, history
        records the step, and old revision IDs keep working as aliases."""
        if self._current():
            return {"status": "current", "schema_version": SCHEMA_VERSION}
        with self.locked():
            return self._migrate()

    def _migrate(self) -> dict:
        if self._current():
            return {"status": "current", "schema_version": SCHEMA_VERSION}
        aliases = {}
        for file in sorted((self.state / "revisions").glob("*.json")):
            data = json.loads(file.read_text())
            if data.get("schema_version") != 1:
                continue
            if hashlib.sha256(canonical_json(data)).hexdigest() != file.stem:
                raise ValueError(f"Revision integrity check failed: {file.stem}")
            score = Score.model_validate(data)
            atomic_json(file.parent / f"{score.revision}.json", score.model_dump(mode="json"))
            aliases[file.stem] = score.revision
        head = json.loads((self.state / "HEAD.json").read_text())["revision"]
        atomic_json(
            self.state / "migrations.json",
            {"from_schema": 1, "to_schema": SCHEMA_VERSION, "revisions": aliases},
        )
        if aliases.get(head, head) != head:
            self._save(self._read(head), head, "migrate score schema 1 to 2")
        atomic_json(self.state / "format.json", {"schema_version": SCHEMA_VERSION})
        return {
            "status": "migrated",
            "schema_version": SCHEMA_VERSION,
            "revision": aliases.get(head, head),
            "revisions": aliases,
        }

    def _resolve(self, revision: str) -> str:
        return self._aliases().get(revision, revision)

    @staticmethod
    def _valid(score: Score):
        report = validate_score(score)
        if report["status"] != "passed":
            raise ValueError(f"Invalid score: {json.dumps(report['findings'])}")

    def _save(self, score: Score, parent: str | None, reason: str):
        atomic_json(
            self.state / "revisions" / f"{score.revision}.json", score.model_dump(mode="json")
        )
        with (self.state / "history.jsonl").open("a") as log:
            log.write(
                json.dumps({"revision": score.revision, "parent": parent, "reason": reason}) + "\n"
            )
            log.flush()
            os.fsync(log.fileno())
        atomic_json(self.state / "HEAD.json", {"revision": score.revision})

    def _protected(self, policy: dict, score: Score) -> bool:
        baseline = self._read(policy["baseline"])
        return all(
            next(t for t in baseline.tracks if t.id == track_id)
            == next(t for t in score.tracks if t.id == track_id)
            for track_id in policy["protected_tracks"]
        )

    def apply_score_patch(
        self,
        expected_revision: str,
        edits: list,
        allowed_measures: list[int],
        reason: str = "edit",
    ) -> dict:
        if not allowed_measures or any(type(m) is not int or m < 1 for m in allowed_measures):
            raise ValueError("Declare positive one-based allowed_measures")
        with self.locked():
            if not self._current():
                self._migrate()
            before = self._read()
            if before.revision != self._resolve(expected_revision):
                raise ValueError("Revision conflict; inspect current HEAD before retrying")
            policy = json.loads((self.state / "policy.json").read_text())
            after = apply_edits(before, edits, set(policy["protected_tracks"]))
            owners = {
                event_id: track_id for event_id, (track_id, _) in before.events_by_id().items()
            }
            moved = [
                event_id
                for event_id, (track_id, _) in after.events_by_id().items()
                if owners.get(event_id, track_id) != track_id
            ]
            if moved:
                raise ValueError(f"Event IDs cannot move between tracks: {moved}")
            outside = sorted(set(changed_measures(before, after)) - set(allowed_measures))
            if outside:
                raise ValueError(f"Edit affects measures outside the authorized passage: {outside}")
            self._valid(after)
            if not self._protected(policy, after):
                raise ValueError("Protected content differs from baseline")
            if after.revision != before.revision:
                self._save(after, before.revision, reason)
            return {"status": "accepted", **compare_revisions(before, after)}

    def rollback(self, expected_revision: str, target_revision: str) -> dict:
        with self.locked():
            if not self._current():
                self._migrate()
            current = self._read()
            if current.revision != self._resolve(expected_revision):
                raise ValueError("Revision conflict")
            target = self._read(target_revision)
            policy = json.loads((self.state / "policy.json").read_text())
            if not self._protected(policy, target):
                raise ValueError("Rollback violates protected content")
            self._valid(target)
            self._save(target, current.revision, "rollback")
            return {"status": "accepted", **compare_revisions(current, target)}
