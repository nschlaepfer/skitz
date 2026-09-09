import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from skitz_music import Event, Project, Score, Track
from skitz_music.analysis import analyze_voice_leading, validate_score
from skitz_music.fixtures import chorale_fixture
from skitz_music.service import MusicService


def test_score_rejects_invalid_notation_and_rhythm():
    for changes in (
        {"pitch": "c4 #(system bad)"},
        {"duration": "0"},
        {"duration": "1/0"},
        {"offset": "0.1"},
        {"pitch": None, "tie": "start"},
    ):
        with pytest.raises(ValueError):
            Event.model_validate(
                {"id": "e1", "offset": "0", "duration": "3", "pitch": "C4", **changes}
            )
    score = chorale_fixture()
    assert validate_score(score)["status"] == "passed"
    assert Event(id="x", offset="0", duration="6/2").duration == "3"


def test_overlap_gap_and_incomplete_measure_are_independent_errors():
    score = Score(
        tracks=(
            Track(
                id="v",
                name="V",
                events=(
                    Event(id="a", offset="1", duration="2", pitch="C4"),
                    Event(id="b", offset="2", duration="2", pitch="D4"),
                ),
            ),
        )
    )
    rules = {finding["rule"] for finding in validate_score(score)["findings"]}
    assert rules == {"implicit_gap", "overlap", "incomplete_measure"}


def test_parallel_detection_reports_correct_events():
    score = Score(
        tracks=tuple(
            Track(
                id=voice,
                name=voice,
                events=tuple(
                    Event(id=f"{voice}{i}", offset=str(i * 3), duration="3", pitch=p)
                    for i, p in enumerate(pitches)
                ),
            )
            for voice, pitches in (("soprano", ["G4", "A4"]), ("bass", ["C3", "D3"]))
        )
    )
    fifths = [
        f for f in analyze_voice_leading(score)["findings"] if f["rule"] == "parallel_perfect_fifth"
    ]
    assert len(fifths) == 1
    assert fifths[0]["from_event_ids"] == ["soprano0", "bass0"]
    assert fifths[0]["to_event_ids"] == ["soprano1", "bass1"]


def test_patch_preserves_protected_track_and_revision_history(tmp_path):
    project = Project(tmp_path)
    before = chorale_fixture()
    project.create(before, ["soprano"])
    result = project.apply_score_patch(
        before.revision, [{"event_id": "bass_002", "set": {"pitch": "D2"}}], [2]
    )
    after = project.read()
    assert result["changed_event_ids"] == ["bass_002"]
    assert "soprano" in result["unchanged_tracks"]
    assert project.read(before.revision) == before
    assert after != before
    project.rollback(after.revision, before.revision)
    assert project.read() == before


@pytest.mark.parametrize(
    "edits,measures",
    [
        ([{"event_id": "soprano_001", "set": {"pitch": "A4"}}], [1]),
        ([{"event_id": "bass_002", "set": {"pitch": "C3"}}], [1]),
        ([{"event_id": "bass_001", "set": {"offset": "3"}}], [1]),
        ([{"event_id": "unknown", "set": {"pitch": "C3"}}], [1]),
        ([{"event_id": "bass_001", "set": {"tie": "start"}}], [1]),
    ],
)
def test_invalid_edits_are_atomic(tmp_path, edits, measures):
    project = Project(tmp_path)
    score = chorale_fixture()
    project.create(score, ["soprano"])
    with pytest.raises(ValueError):
        project.apply_score_patch(score.revision, edits, measures)
    assert project.read() == score
    assert len((project.state / "history.jsonl").read_text().splitlines()) == 1


def test_concurrent_stale_patch_is_rejected(tmp_path):
    score = chorale_fixture()
    Project(tmp_path).create(score)

    def edit(value):
        try:
            Project(tmp_path).apply_score_patch(
                score.revision, [{"event_id": "bass_002", "set": {"pitch": value}}], [2]
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, ["E3", "F3"])) == [False, True]


def test_revision_hash_detects_tampering(tmp_path):
    score = chorale_fixture()
    project = Project(tmp_path)
    project.create(score)
    file = project.state / "revisions" / f"{score.revision}.json"
    data = json.loads(file.read_text())
    data["title"] = "tampered"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity"):
        project.read()


def test_service_confines_paths_and_symlinks(tmp_path):
    service = MusicService(tmp_path / "music")
    service.workspace.mkdir()
    (service.workspace / "outside").symlink_to(tmp_path, target_is_directory=True)
    for path in ("../secret", "outside/secret", "/etc/passwd"):
        with pytest.raises(ValueError, match="escapes"):
            service.path(path)
