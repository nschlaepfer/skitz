"""Immutable score revisions with optimistic concurrency and persistent edit constraints."""

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

from .analysis import compare_revisions, validate_score
from .score import Score


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
            atomic_json(
                self.state / "policy.json",
                {"protected_tracks": protected, "baseline": score.revision},
            )
            self._save(score, parent=None, reason="create")
        return {"revision": score.revision, "status": "created", "protected_tracks": protected}

    def read(self, revision: str | None = None) -> Score:
        revision = revision or json.loads((self.state / "HEAD.json").read_text())["revision"]
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("Invalid revision")
        score = Score.model_validate_json(
            (self.state / "revisions" / f"{revision}.json").read_text()
        )
        if score.revision != revision:
            raise ValueError("Revision integrity check failed")
        return score

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

    def apply_score_patch(
        self,
        expected_revision: str,
        edits: list[dict],
        allowed_measures: list[int],
        reason: str = "edit",
    ) -> dict:
        if not allowed_measures or any(type(m) is not int or m < 1 for m in allowed_measures):
            raise ValueError("Declare positive one-based allowed_measures")
        if len({e.get("event_id") for e in edits}) != len(edits):
            raise ValueError("Duplicate event edits")
        with self.locked():
            before = self.read()
            if before.revision != expected_revision:
                raise ValueError("Revision conflict; inspect current HEAD before retrying")
            policy = json.loads((self.state / "policy.json").read_text())
            baseline = self.read(policy["baseline"])
            data = before.model_dump(mode="json")
            lookup = {e["id"]: (t, e) for t in data["tracks"] for e in t["events"]}
            for edit in edits:
                if (
                    set(edit) != {"event_id", "set"}
                    or not edit["set"]
                    or not set(edit["set"]) <= {"pitch", "articulation", "tie"}
                ):
                    raise ValueError(
                        "Patch requires event_id and set of pitch, articulation, or tie"
                    )
                if edit["event_id"] not in lookup:
                    raise ValueError("Unknown event ID")
                track, event = lookup[edit["event_id"]]
                if track["id"] in policy["protected_tracks"]:
                    raise ValueError(f"Protected track: {track['id']}")
                start = Fraction(event["offset"])
                end = start + Fraction(event["duration"])
                first = int(start // before.bar_length) + 1
                last = int(-(-end // before.bar_length))
                if not set(range(first, last + 1)) <= set(allowed_measures):
                    raise ValueError("Edit affects a measure outside the authorized passage")
                event.update(edit["set"])
            after = Score.model_validate(data)
            self._valid(after)
            for track_id in policy["protected_tracks"]:
                if next(t for t in baseline.tracks if t.id == track_id) != next(
                    t for t in after.tracks if t.id == track_id
                ):
                    raise ValueError("Protected content differs from baseline")
            if after.revision != before.revision:
                self._save(after, before.revision, reason)
            return {"status": "accepted", **compare_revisions(before, after)}

    def rollback(self, expected_revision: str, target_revision: str) -> dict:
        with self.locked():
            current = self.read()
            if current.revision != expected_revision:
                raise ValueError("Revision conflict")
            target = self.read(target_revision)
            policy = json.loads((self.state / "policy.json").read_text())
            baseline = self.read(policy["baseline"])
            for track_id in policy["protected_tracks"]:
                if next(t for t in target.tracks if t.id == track_id) != next(
                    t for t in baseline.tracks if t.id == track_id
                ):
                    raise ValueError("Rollback violates protected content")
            self._valid(target)
            self._save(target, current.revision, "rollback")
            return {"status": "accepted", **compare_revisions(current, target)}
