import pytest
from skitz_music import Event, Project, Score, Track
from skitz_music.analysis import validate_score

MELODY = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]
MELODY += ["C5", "B4", "A4", "G4", "F4", "E4", "D4", "C4"]


def song() -> Score:
    """Four 4/4 measures: a quarter-note melody over a protected whole-note bass."""
    return Score(
        title="Patch test",
        key="c major",
        meter="4/4",
        tempo=100,
        tracks=(
            Track(
                id="melody",
                name="Melody",
                events=tuple(
                    Event(id=f"m{i + 1:02}", offset=str(i), duration="1", pitch=p)
                    for i, p in enumerate(MELODY)
                ),
            ),
            Track(
                id="bass",
                name="Bass",
                events=tuple(
                    Event(id=f"b{i + 1}", offset=str(i * 4), duration="4", pitch=p)
                    for i, p in enumerate(["C3", "F3", "G3", "C3"])
                ),
            ),
        ),
    )


@pytest.fixture
def project(tmp_path):
    store = Project(tmp_path / "piece")
    store.create(song(), ["bass"])
    return store


def patch(project, edits, measures, **kwargs):
    return project.apply_score_patch(project.read().revision, edits, measures, **kwargs)


def events(project, track="melody"):
    return {e.id: e for t in project.read().tracks if t.id == track for e in t.events}


def assert_rejected(project, edits, measures, match):
    before = project.read()
    history = (project.state / "history.jsonl").read_text()
    with pytest.raises(ValueError, match=match):
        project.apply_score_patch(before.revision, edits, measures)
    assert project.read() == before
    assert (project.state / "history.jsonl").read_text() == history


def test_set_duration_and_insert_keep_untouched_ids(project):
    before = project.read()
    result = patch(
        project,
        [
            {"op": "set", "event_id": "m02", "set": {"duration": "1/2"}},
            {
                "op": "insert",
                "track_id": "melody",
                "event": {"id": "m02b", "offset": "3/2", "duration": "1/2", "pitch": "D#4"},
            },
        ],
        [1],
    )
    assert result["changed_event_ids"] == ["m02", "m02b"]
    assert result["added_event_ids"] == ["m02b"]
    assert result["changed_measures"] == [1]
    assert "bass" in result["unchanged_tracks"]
    after = events(project)
    assert after["m02b"].start == after["m02"].end
    untouched = {k: v for k, v in before.events_by_id().items() if k not in {"m02", "m02b"}}
    assert {k: project.read().events_by_id()[k] for k in untouched} == untouched


def test_delete_and_insert_chord(project):
    result = patch(
        project,
        [
            {"op": "delete", "event_id": "m06"},
            {
                "op": "insert",
                "track_id": "melody",
                "event": {"id": "c1", "offset": "5", "duration": "1", "pitches": ["E4", "C4"]},
            },
        ],
        [2],
    )
    assert result["removed_event_ids"] == ["m06"]
    assert events(project)["c1"].pitches == ("C4", "E4")


def test_delete_without_refill_leaves_a_gap(project):
    assert_rejected(project, [{"op": "delete", "event_id": "m06"}], [2], "implicit_gap")


def test_split_restrikes_or_ties(project):
    patch(
        project,
        [
            {"op": "split", "event_id": "m05", "durations": ["1/2", "1/2"], "new_ids": ["m05b"]},
            {
                "op": "split",
                "event_id": "m06",
                "durations": ["3/4", "1/4"],
                "new_ids": ["m06b"],
                "tie": True,
            },
        ],
        [2],
    )
    after = events(project)
    assert (after["m05"].duration, after["m05b"].offset, after["m05b"].pitches) == (
        "1/2",
        "9/2",
        ("G4",),
    )
    assert after["m05"].tie is None and after["m05b"].tie is None
    assert (after["m06"].tie, after["m06b"].tie) == ("start", "stop")


def test_split_keeps_outer_ties_and_checks_lengths(project):
    patch(
        project,
        [
            {"event_id": "m04", "set": {"pitch": "E4", "tie": "start"}},
            {"event_id": "m03", "set": {"tie": "start"}},
            {"event_id": "m04", "set": {"tie": "continue"}},
            {"event_id": "m05", "set": {"pitch": "E4", "tie": "stop"}},
        ],
        [1, 2],
    )
    patch(
        project,
        [{"op": "split", "event_id": "m04", "durations": ["1/2", "1/2"], "new_ids": ["m04b"]}],
        [1],
    )
    after = events(project)
    assert (after["m04"].tie, after["m04b"].tie) == ("stop", "start")
    assert_rejected(
        project,
        [{"op": "split", "event_id": "m07", "durations": ["1/2", "1/4"], "new_ids": ["x"]}],
        [2],
        "add up",
    )


def test_merge_joins_back_to_back_events(project):
    result = patch(project, [{"op": "merge", "event_ids": ["m08", "m07"]}], [2])
    after = events(project)
    assert "m08" not in after
    assert (after["m07"].offset, after["m07"].duration, after["m07"].pitches) == ("6", "2", ("B4",))
    assert result["removed_event_ids"] == ["m08"]
    assert_rejected(project, [{"op": "merge", "event_ids": ["m01", "m03"]}], [1], "back to back")


def test_replace_rewrites_a_passage_with_new_rhythm(project):
    before = project.read()
    result = patch(
        project,
        [
            {
                "op": "replace",
                "track_id": "melody",
                "measures": [3],
                "events": [
                    {"id": "m09", "duration": "3/2", "pitch": "C5"},
                    {"id": "r1", "duration": "1/2", "pitches": []},
                    {"id": "t1", "duration": "1/3", "pitch": "A4"},
                    {"id": "t2", "duration": "1/3", "pitch": "B4"},
                    {"id": "t3", "duration": "1/3", "pitch": "A4"},
                    {"id": "n1", "duration": "1", "pitches": ["G4", "B4", "D5"]},
                ],
            }
        ],
        [3],
    )
    after = events(project)
    assert [after[i].offset for i in ("m09", "r1", "t1", "t2", "t3", "n1")] == [
        "8",
        "19/2",
        "10",
        "31/3",
        "32/3",
        "11",
    ]
    assert set(result["removed_event_ids"]) == {"m10", "m11", "m12"}
    assert result["changed_measures"] == [3]
    for event_id in ("m08", "m13"):
        assert after[event_id] == before.events_by_id()[event_id][1]
    assert validate_score(project.read())["status"] == "passed"


def test_replace_must_fill_measures_and_respect_barlines(project):
    one = [{"id": "m09", "duration": "3", "pitch": "C5"}]
    assert_rejected(
        project,
        [{"op": "replace", "track_id": "melody", "measures": [3], "events": one}],
        [3],
        "hold 4",
    )
    patch(project, [{"op": "merge", "event_ids": ["m08", "m09"]}], [2, 3])
    whole = [{"id": "x1", "duration": "4", "pitch": "C5"}]
    assert_rejected(
        project,
        [{"op": "replace", "track_id": "melody", "measures": [3], "events": whole}],
        [2, 3],
        "split it at the barline",
    )
    assert_rejected(
        project,
        [{"op": "replace", "track_id": "melody", "measures": [3, 1], "events": whole}],
        [1, 3],
        "without gaps",
    )


def test_replaced_ids_cannot_collide(project):
    clash = [{"id": "m01", "duration": "4", "pitch": "C5"}]
    assert_rejected(
        project,
        [{"op": "replace", "track_id": "melody", "measures": [3], "events": clash}],
        [3],
        "already used",
    )


def test_transpose_measure_range_and_whole_track(project):
    patch(
        project, [{"op": "transpose", "track_id": "melody", "interval": "M2", "measures": [2]}], [2]
    )
    after = events(project)
    assert [after[f"m0{i}"].pitches[0] for i in range(5, 9)] == ["A4", "B4", "C#5", "D5"]
    assert after["m04"].pitches == ("F4",)
    assert_rejected(
        project,
        [{"op": "transpose", "track_id": "melody", "interval": "-P8"}],
        [1, 2],
        r"outside the authorized passage: \[3, 4\]",
    )
    patch(project, [{"op": "transpose", "track_id": "melody", "interval": "-P8"}], [1, 2, 3, 4])
    assert events(project)["m01"].pitches == ("C3",)


def test_transpose_rejects_bad_intervals_and_spellings(project):
    assert_rejected(
        project, [{"op": "transpose", "track_id": "melody", "interval": "P3"}], [1], "interval"
    )
    patch(project, [{"event_id": "m01", "set": {"pitch": "F##4"}}], [1])
    assert_rejected(
        project,
        [{"op": "transpose", "track_id": "melody", "interval": "A1", "measures": [1]}],
        [1],
        "cannot store",
    )


def test_tempo_change_covers_every_affected_measure(project):
    edit = [{"op": "set_tempo", "measure": 3, "bpm": 140}]
    assert_rejected(project, edit, [3], r"outside the authorized passage: \[4\]")
    result = patch(project, edit, [3, 4])
    score = project.read()
    assert [c.model_dump() for c in score.tempo_map] == [
        {"measure": 1, "bpm": 100},
        {"measure": 3, "bpm": 140},
    ]
    assert result["changed_event_ids"] == [] and result["metadata_changed"]
    patch(project, [{"op": "set_tempo", "measure": 3, "bpm": None}], [3, 4])
    assert len(project.read().tempo_map) == 1
    assert_rejected(project, [{"op": "set_tempo", "measure": 1, "bpm": None}], [1], "Measure 1")


def test_meter_regrouping_keeps_protected_bass(project):
    edit = [{"op": "set_meter", "measure": 3, "meter": "2/2"}]
    assert_rejected(project, edit, [3], r"\[4\]")
    patch(project, edit, [3, 4])
    score = project.read()
    assert [c.meter for c in score.meter_map] == ["4/4", "2/2"]
    assert score.tracks[1] == song().tracks[1]


def test_meter_change_with_new_bar_contents(tmp_path):
    project = Project(tmp_path / "free")
    project.create(song())
    patch(
        project,
        [
            {"op": "set_meter", "measure": 4, "meter": "3/4"},
            {"op": "delete", "event_id": "m16"},
            {
                "op": "replace",
                "track_id": "melody",
                "measures": [4],
                "events": [
                    {"id": "m13", "duration": "1", "pitch": "E4"},
                    {"id": "m14", "duration": "2", "pitch": "C4"},
                ],
            },
            {
                "op": "replace",
                "track_id": "bass",
                "measures": [4],
                "events": [{"id": "b4", "duration": "3", "pitch": "C3"}],
            },
        ],
        [4],
    )
    score = project.read()
    assert score.end == 15
    assert validate_score(score)["status"] == "passed"


@pytest.mark.parametrize(
    "edits,measures,match",
    [
        ([{"event_id": "b2", "set": {"pitch": "A2"}}], [2], "Protected track: bass"),
        ([{"op": "delete", "event_id": "b2"}], [2], "Protected track: bass"),
        (
            [{"op": "split", "event_id": "b2", "durations": ["2", "2"], "new_ids": ["x"]}],
            [2],
            "Protected track: bass",
        ),
        ([{"op": "merge", "event_ids": ["b1", "b2"]}], [1, 2], "Protected track: bass"),
        (
            [
                {
                    "op": "replace",
                    "track_id": "bass",
                    "measures": [2],
                    "events": [{"id": "b2", "duration": "4", "pitch": "D3"}],
                }
            ],
            [2],
            "Protected track: bass",
        ),
        (
            [{"op": "transpose", "track_id": "bass", "interval": "P8", "measures": [2]}],
            [2],
            "Protected track: bass",
        ),
        (
            [
                {
                    "op": "insert",
                    "track_id": "bass",
                    "event": {"id": "x", "offset": "16", "duration": "4", "pitch": "C3"},
                }
            ],
            [5],
            "Protected track: bass",
        ),
    ],
)
def test_protected_track_rejects_every_edit_type(project, edits, measures, match):
    assert_rejected(project, edits, measures, match)


@pytest.mark.parametrize(
    "edits,measures,match",
    [
        (
            [{"event_id": "m05", "set": {"duration": "2"}}, {"op": "delete", "event_id": "m06"}],
            [1],
            r"\[2\]",
        ),
        ([{"op": "merge", "event_ids": ["m04", "m05"]}], [1], r"\[2\]"),
        ([{"op": "delete", "event_id": "m01"}], [1], "implicit_gap"),
        ([{"op": "set", "event_id": "m01", "set": {"offset": "3"}}], [1], "offset"),
        ([{"op": "explode", "event_id": "m01"}], [1], "explode"),
        ([{"event_id": "m01", "set": {}}], [1], "set needs"),
        ([{"event_id": "m01", "set": {"pitch": "C4", "pitches": ["C4"]}}], [1], "not both"),
        ([{"event_id": "m01", "set": {"pitches": ["C4", "B#3"]}}], [1], "enharmonic"),
    ],
)
def test_invalid_rhythm_edits_are_atomic(project, edits, measures, match):
    assert_rejected(project, edits, measures, match)


def test_stale_revision_and_rollback_cover_rhythm_edits(project):
    first = project.read()
    patch(project, [{"op": "merge", "event_ids": ["m01", "m02"]}], [1])
    with pytest.raises(ValueError, match="Revision conflict"):
        project.apply_score_patch(first.revision, [{"op": "delete", "event_id": "m03"}], [1])
    project.rollback(project.read().revision, first.revision)
    assert project.read() == first
    reasons = [line for line in (project.state / "history.jsonl").read_text().splitlines()]
    assert len(reasons) == 3
