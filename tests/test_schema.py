import hashlib
import json
import subprocess
import sys

import pytest
from skitz_music import Event, Project, Score
from skitz_music.analysis import inspect_score, validate_score
from skitz_music.fixtures import chorale_fixture
from skitz_music.score import canonical_json
from skitz_music.store import atomic_json
from skitz_music.verification import verify_project


def line(*events, meter_map=None, tempo_map=None) -> Score:
    maps = {"meter_map": meter_map or [{"measure": 1, "meter": "4/4"}]}
    if tempo_map:
        maps["tempo_map"] = tempo_map
    return Score.model_validate(
        {**maps, "tracks": [{"id": "v", "name": "V", "events": list(events)}]}
    )


def test_chords_are_normalized_and_checked():
    chord = Event(id="c", offset="0", duration="4", pitches=["G4", "C4", "E-4"])
    assert chord.pitches == ("C4", "E-4", "G4")
    assert Event(id="n", offset="0", duration="1", pitch="A4").pitches == ("A4",)
    assert Event(id="r", offset="0", duration="1", pitch=None).pitches == ()
    for bad in (
        ["C4", "C4"],
        ["C4", "B#3"],
        ["H4"],
        [f"C{i}" for i in range(9)] + ["D4", "E4", "F4", "G4"],
    ):
        with pytest.raises(ValueError):
            Event(id="x", offset="0", duration="1", pitches=bad)
    with pytest.raises(ValueError, match="not both"):
        Event.model_validate(
            {"id": "x", "offset": "0", "duration": "1", "pitch": "C4", "pitches": []}
        )


def test_chord_ties_need_the_same_pitches():
    tied = line(
        {"id": "a", "offset": "0", "duration": "2", "pitches": ["C4", "E4"], "tie": "start"},
        {"id": "b", "offset": "2", "duration": "2", "pitches": ["E4", "C4"], "tie": "stop"},
    )
    assert validate_score(tied)["status"] == "passed"
    broken = line(
        {"id": "a", "offset": "0", "duration": "2", "pitches": ["C4", "E4"], "tie": "start"},
        {"id": "b", "offset": "2", "duration": "2", "pitches": ["C4", "F4"], "tie": "stop"},
    )
    rules = {f["rule"] for f in validate_score(broken)["findings"]}
    assert rules == {"orphan_tie_start", "orphan_tie_stop"}


def test_maps_must_start_at_one_increase_and_change():
    note = {"id": "a", "offset": "0", "duration": "4", "pitch": "C4"}
    for meter_map in (
        [{"measure": 2, "meter": "4/4"}],
        [{"measure": 1, "meter": "4/4"}, {"measure": 1, "meter": "3/4"}],
        [{"measure": 1, "meter": "4/4"}, {"measure": 2, "meter": "4/4"}],
        [{"measure": 1, "meter": "5/3"}],
    ):
        with pytest.raises(ValueError):
            line(note, meter_map=meter_map)
    with pytest.raises(ValueError, match="not both"):
        Score.model_validate({"meter": "4/4", "meter_map": [], "tracks": []})
    with pytest.raises(ValueError):
        line(note, tempo_map=[{"measure": 1, "bpm": 90}, {"measure": 3, "bpm": 90}])


def test_measure_grid_follows_meter_changes():
    score = line(
        {"id": "a", "offset": "0", "duration": "4", "pitch": "C4"},
        {"id": "b", "offset": "4", "duration": "3", "pitch": "D4"},
        {"id": "c", "offset": "7", "duration": "3/2", "pitch": "E4"},
        {"id": "d", "offset": "17/2", "duration": "3/2", "pitch": "F4"},
        {"id": "e", "offset": "10", "duration": "3", "pitches": ["G4", "B4"]},
        meter_map=[
            {"measure": 1, "meter": "4/4"},
            {"measure": 2, "meter": "3/4"},
            {"measure": 3, "meter": "6/8"},
        ],
        tempo_map=[{"measure": 1, "bpm": 80}, {"measure": 3, "bpm": 120}],
    )
    assert validate_score(score)["status"] == "passed"
    report = inspect_score(score)
    assert report["measures"] == 4
    assert [(m["start"], m["meter"], m["bpm"]) for m in report["measure_grid"]] == [
        ("0", "4/4", 80),
        ("4", "3/4", 80),
        ("7", "6/8", 120),
        ("10", "6/8", 120),
    ]
    assert [e["measures"] for e in report["tracks"][0]["events"]][2:] == [[3, 3], [3, 3], [4, 4]]
    short = line(
        {"id": "a", "offset": "0", "duration": "4", "pitch": "C4"},
        {"id": "b", "offset": "4", "duration": "4", "pitch": "D4"},
        meter_map=[{"measure": 1, "meter": "4/4"}, {"measure": 2, "meter": "3/4"}],
        tempo_map=[{"measure": 1, "bpm": 80}, {"measure": 9, "bpm": 120}],
    )
    findings = validate_score(short)["findings"]
    assert {f["rule"] for f in findings} == {"incomplete_measure", "map_change_beyond_end"}


def v1_document(score: Score) -> dict:
    """The exact JSON a schema-1 Skitz wrote for an equivalent single-pitch score."""
    return {
        "schema_version": 1,
        "title": score.title,
        "meter": score.meter_map[0].meter,
        "tempo": score.tempo_map[0].bpm,
        "key": score.key,
        "tracks": [
            {
                "id": t.id,
                "name": t.name,
                "program": t.program,
                "events": [
                    {
                        "id": e.id,
                        "offset": e.offset,
                        "duration": e.duration,
                        "pitch": e.pitches[0] if e.pitches else None,
                        "tie": e.tie,
                        "articulation": e.articulation,
                    }
                    for e in t.events
                ],
            }
            for t in score.tracks
        ],
    }


def v1_project(path, scores: list[Score], protected: list[str]) -> list[str]:
    """Write a project the way schema-1 Skitz stored it and return its revision IDs."""
    state = path / ".skitz"
    ids, parent = [], None
    for score in scores:
        data = v1_document(score)
        revision = hashlib.sha256(canonical_json(data)).hexdigest()
        atomic_json(state / "revisions" / f"{revision}.json", data)
        with (state / "history.jsonl").open("a") as log:
            log.write(json.dumps({"revision": revision, "parent": parent, "reason": "v1"}) + "\n")
        ids.append(revision)
        parent = revision
    atomic_json(state / "policy.json", {"protected_tracks": protected, "baseline": ids[0]})
    atomic_json(state / "HEAD.json", {"revision": ids[-1]})
    return ids


def test_schema_one_document_migrates_losslessly():
    score = chorale_fixture()
    assert Score.model_validate(v1_document(score)) == score
    assert Score.model_validate_json(json.dumps(v1_document(score))).schema_version == 2


def test_schema_one_project_migrates_on_read(tmp_path):
    first = chorale_fixture()
    edited = Project(tmp_path / "scratch")
    edited.create(first)
    edited.apply_score_patch(
        first.revision, [{"event_id": "bass_002", "set": {"pitch": "A2"}}], [2]
    )
    second = edited.read()
    old_first, old_second = v1_project(tmp_path / "piece", [first, second], ["soprano"])
    project = Project(tmp_path / "piece")
    assert project.read() == second
    state = project.state
    assert json.loads((state / "format.json").read_text()) == {"schema_version": 2}
    assert json.loads((state / "HEAD.json").read_text())["revision"] == second.revision
    assert json.loads((state / "migrations.json").read_text())["revisions"] == {
        old_first: first.revision,
        old_second: second.revision,
    }
    history = [json.loads(x) for x in (state / "history.jsonl").read_text().splitlines()]
    assert history[-1] == {
        "revision": second.revision,
        "parent": old_second,
        "reason": "migrate score schema 1 to 2",
    }
    assert (state / "revisions" / f"{old_first}.json").is_file()
    assert project.read(old_first) == first
    assert project.migrate()["status"] == "current"
    project.apply_score_patch(old_second, [{"event_id": "bass_002", "set": {"pitch": "D3"}}], [2])
    assert project.read() == first
    with pytest.raises(ValueError, match="Protected track"):
        project.apply_score_patch(
            first.revision, [{"event_id": "soprano_001", "set": {"pitch": "A4"}}], [1]
        )
    project.rollback(first.revision, old_second)
    assert project.read() == second
    assert "Protected tracks changed" not in verify_project(project.path)["errors"]


def test_tampered_schema_one_revision_blocks_migration(tmp_path):
    ids = v1_project(tmp_path, [chorale_fixture()], [])
    file = tmp_path / ".skitz" / "revisions" / f"{ids[0]}.json"
    data = json.loads(file.read_text())
    data["title"] = "tampered"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity"):
        Project(tmp_path).read()
    assert not (tmp_path / ".skitz" / "format.json").exists()
    assert json.loads((tmp_path / ".skitz" / "HEAD.json").read_text())["revision"] == ids[0]


def test_new_projects_are_current(tmp_path):
    project = Project(tmp_path)
    project.create(chorale_fixture())
    assert project.migrate() == {"status": "current", "schema_version": 2}
    assert not (project.state / "migrations.json").exists()


@pytest.mark.parametrize("kind,expected", [("score", "meter_map"), ("patch", "allowed_measures")])
def test_cli_prints_score_and_patch_schemas(kind, expected):
    result = subprocess.run(
        [sys.executable, "-m", "skitz_music.cli", "schema", kind],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    schema = json.loads(result.stdout)
    assert expected in schema["properties"]
    if kind == "patch":
        assert {"SplitEdit", "MergeEdit", "ReplaceEdit", "TransposeEdit"} <= set(schema["$defs"])


def test_cli_migrate_reports_status(tmp_path):
    v1_project(tmp_path, [chorale_fixture()], [])
    result = subprocess.run(
        [sys.executable, "-m", "skitz_music.cli", "migrate", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "migrated"


def test_cli_patch_file_applies_rhythm_edits(tmp_path):
    project = Project(tmp_path / "piece")
    project.create(chorale_fixture(), ["soprano"])
    request = {
        "expected_revision": project.read().revision,
        "edits": [
            {"op": "split", "event_id": "alto_001", "durations": ["2", "1"], "new_ids": ["a1b"]},
            {"event_id": "a1b", "set": {"pitches": ["C4"]}},
        ],
        "allowed_measures": [1],
        "reason": "passing tone",
    }
    (tmp_path / "patch.json").write_text(json.dumps(request))
    command = [sys.executable, "-m", "skitz_music.cli", "patch", str(project.path)]
    result = subprocess.run(
        [*command, str(tmp_path / "patch.json")], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["added_event_ids"] == ["a1b"]
    (tmp_path / "bad.json").write_text(json.dumps({**request, "edits": [{"op": "nope"}]}))
    result = subprocess.run(
        [*command, str(tmp_path / "bad.json")], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 1 and "nope" in result.stderr
