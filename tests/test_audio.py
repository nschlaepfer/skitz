import hashlib
import json

import httpx
import pytest
from skitz_music import playback, soundfonts
from skitz_music.fixtures import chorale_fixture
from skitz_music.render import render_score
from skitz_music.store import Project

FONT = b"RIFF" + b"\x00" * 4 + b"sfbk" + b"fake soundfont"
LICENSE = b"GeneralUser GS license text"


@pytest.fixture
def font_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SKITZ_SOUNDFONT_DIR", str(tmp_path / "soundfonts"))
    monkeypatch.delenv("SKITZ_SOUNDFONT", raising=False)
    pinned = {
        **soundfonts.GENERALUSER,
        "bytes": len(FONT),
        "sha256": hashlib.sha256(FONT).hexdigest(),
        "license_sha256": hashlib.sha256(LICENSE).hexdigest(),
    }
    monkeypatch.setattr(soundfonts, "GENERALUSER", pinned)
    return tmp_path / "soundfonts"


def serve(font=FONT):
    def handler(request):
        if request.url.path.endswith("LICENSE.txt"):
            return httpx.Response(200, content=LICENSE)
        return httpx.Response(200, content=font)

    return httpx.MockTransport(handler)


def test_install_verifies_and_is_idempotent(font_home):
    result = soundfonts.install(transport=serve())
    assert result["status"] == "installed"
    assert (font_home / "GeneralUser-GS.sf2").read_bytes() == FONT
    assert (font_home / "GeneralUser-GS-LICENSE.txt").read_bytes() == LICENSE
    meta = json.loads((font_home / "GeneralUser-GS.json").read_text())
    assert meta["commit"] == soundfonts.GENERALUSER_COMMIT
    assert soundfonts.install(transport=serve())["status"] == "already_installed"


def test_install_rejects_a_file_that_does_not_match_the_pin(font_home):
    with pytest.raises(RuntimeError, match="did not match"):
        soundfonts.install(transport=serve(font=b"tampered" * 4))
    assert not (font_home / "GeneralUser-GS.sf2").exists()
    assert not list(font_home.glob("*.part"))


def test_soundfont_lookup_order(font_home, tmp_path, monkeypatch):
    assert soundfonts.default_soundfont() is None
    soundfonts.install(transport=serve())
    assert soundfonts.default_soundfont() == font_home / "GeneralUser-GS.sf2"
    custom = tmp_path / "mine.sf2"
    custom.write_bytes(FONT)
    monkeypatch.setenv("SKITZ_SOUNDFONT", str(custom))
    assert soundfonts.default_soundfont() == custom
    assert soundfonts.status()["source"] == "SKITZ_SOUNDFONT"


def test_render_skips_audio_with_a_hint_when_no_soundfont(font_home, tmp_path):
    report = render_score(chorale_fixture(), tmp_path / "out", engrave=False)
    assert report["status"] == "passed"
    assert "skitz soundfont install" in report["audio_skipped"]
    assert "score.wav" not in report["artifacts"]


def test_render_fails_when_an_explicit_soundfont_is_missing(font_home, tmp_path):
    report = render_score(
        chorale_fixture(), tmp_path / "out", soundfont=str(tmp_path / "nope.sf2"), engrave=False
    )
    assert report["status"] == "failed"
    assert any("SoundFont not found" in error for error in report["errors"])


def _project_with_render(tmp_path):
    project = Project(tmp_path / "piece")
    project.create(chorale_fixture(), ["soprano"])
    revision = project.read().revision
    old = project.path / "renders/old"
    new = project.path / "renders/new"
    for folder, rev in ((old, "0" * 64), (new, revision)):
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"revision": rev}))
        (folder / "score.wav").write_bytes(b"RIFF")
    return project, new / "score.wav"


def test_play_finds_the_render_of_the_current_revision(tmp_path):
    project, wav = _project_with_render(tmp_path)
    assert playback.resolve(project.path) == wav.resolve()
    with pytest.raises(ValueError, match="Not an audio file"):
        playback.resolve(tmp_path / "missing.txt")


def test_project_without_audio_render_explains_what_to_do(tmp_path):
    project = Project(tmp_path / "piece")
    project.create(chorale_fixture(), ["soprano"])
    with pytest.raises(ValueError, match="Render it first"):
        playback.resolve(project.path)


def test_background_play_and_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("SKITZ_STATE", str(tmp_path / "state"))
    _, wav = _project_with_render(tmp_path)
    monkeypatch.setattr(playback, "player_command", lambda path: ["sleep", "30"])
    result = playback.play(wav, background=True)
    assert result["status"] == "playing"
    assert playback.stop()["status"] == "stopped"
    assert playback.stop()["status"] == "nothing_playing"


def test_playback_service_is_confined_to_the_workspace(tmp_path):
    service = playback.PlaybackService(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        service.play_audio("../outside.wav")
