import pytest
from skitz_music.analysis import validate_score
from skitz_music.importers import import_notation


def test_abc_import_preserves_pitch_and_rhythm(tmp_path):
    abc = tmp_path / "phrase.abc"
    abc.write_text("X:1\nT:Phrase\nM:3/4\nL:1/4\nQ:1/4=90\nK:Gm\nGAB | c3 |\n")
    score = import_notation(abc)
    assert score.meter == "3/4"
    assert [e.pitch for e in score.tracks[0].events] == ["G4", "A4", "B-4", "C5"]
    assert [e.duration for e in score.tracks[0].events] == ["1", "1", "1", "3"]
    assert validate_score(score)["status"] == "passed"


def test_chords_do_not_silently_lose_notes(tmp_path):
    abc = tmp_path / "chords.abc"
    abc.write_text("X:1\nM:3/4\nL:1/4\nK:C\n[CEG]3 |\n")
    with pytest.raises(ValueError, match="chords"):
        import_notation(abc)
