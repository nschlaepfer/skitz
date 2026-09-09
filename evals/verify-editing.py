"""Deterministic harness acceptance. This does not call a model or measure composition quality."""

import argparse
import json
from pathlib import Path

from skitz_music import Project
from skitz_music.analysis import analyze_voice_leading, compare_revisions
from skitz_music.fixtures import chorale_fixture
from skitz_music.render import render_score
from skitz_music.store import atomic_json

parser = argparse.ArgumentParser()
parser.add_argument("output")
parser.add_argument("--soundfont", required=True)
args = parser.parse_args()
output = Path(args.output).resolve()
project = Project(output / "piece")
before = chorale_fixture()
project.create(before, ["soprano"])
baseline = analyze_voice_leading(before)
project.apply_score_patch(
    before.revision, [{"event_id": "bass_002", "set": {"pitch": "A2"}}], [2], "inject octave"
)
broken = project.read()
diagnostics = analyze_voice_leading(broken)
target = [
    f
    for f in diagnostics["findings"]
    if f["rule"] == "parallel_octave"
    and f.get("voices") == ["soprano", "bass"]
    and f.get("offset") == "3"
]
assert target, "Injected octave was not detected"
project.apply_score_patch(
    broken.revision, [{"event_id": "bass_002", "set": {"pitch": "D3"}}], [2], "repair octave"
)
after = project.read()
assert before == after, "Repair changed unaffected content"
assert compare_revisions(broken, after)["changed_event_ids"] == ["bass_002"]
assert analyze_voice_leading(after) == baseline
renders = [
    render_score(score, project.path / "renders", args.soundfont)
    for score in (before, broken, after)
]
assert all(render["status"] == "passed" for render in renders), renders
report = {
    "kind": "deterministic-harness-acceptance",
    "model_called": False,
    "passed": True,
    "baseline": before.revision,
    "injected": broken.revision,
    "repaired": after.revision,
    "protected_soprano_unchanged": True,
    "changed_event_ids": ["bass_002"],
    "injected_findings": target,
    "baseline_style_findings": baseline["findings"],
    "renders": renders,
}
atomic_json(output / "acceptance.json", report)
print(json.dumps({"passed": True, "report": str(output / "acceptance.json")}, indent=2))
