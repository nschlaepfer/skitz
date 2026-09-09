import json
import shutil
import sys
from pathlib import Path

import pytest
from music21 import converter
from skitz_music.fixtures import chorale_fixture
from skitz_music.render import lilypond_source, render_score, restricted_run


def test_midi_and_musicxml_are_parseable_and_manifest_matches(tmp_path):
    score = chorale_fixture()
    report = render_score(score, tmp_path, audio=False, engrave=False)
    output = Path(report["output_directory"])
    assert report["status"] == "passed"
    for name in ("score.mid", "score.musicxml"):
        parsed = converter.parse(output / name)
        assert len(parsed.parts) == 4
        assert len(parsed.recurse().notes) == 24
    assert json.loads((output / "manifest.json").read_text())["revision"] == score.revision
    assert lilypond_source(score).count("\\new Staff <<") == 2


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("lilypond"), reason="macOS LilyPond required"
)
def test_real_engraving(tmp_path):
    report = render_score(chorale_fixture(), tmp_path, audio=False)
    assert report["status"] == "passed", report
    assert (Path(report["output_directory"]) / "score.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox required")
def test_renderer_cannot_read_private_file(tmp_path):
    private = tmp_path / "secret.txt"
    private.write_text("should-never-be-readable")
    work = tmp_path / "worker"
    work.mkdir()
    control = restricted_run(["/bin/echo", "sandbox-alive"], work)
    assert control["exit_code"] == 0
    assert "sandbox-alive" in control["diagnostics"]
    result = restricted_run(["/bin/cat", str(private)], work)
    assert result["exit_code"] != 0
    assert "should-never-be-readable" not in result["diagnostics"]
