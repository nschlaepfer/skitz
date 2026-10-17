import asyncio
import base64
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from skitz_music import samples, suno, suno_cli, suno_inbox


def fake_jwt() -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 60}).encode())
    return f"header.{claims.decode().rstrip('=')}.signature"


class FakeSuno:
    """In-memory stand-in for Clerk, the studio API and the audio CDN."""

    def __init__(self):
        self.jwt = fake_jwt()
        self.polls = 0
        self.captcha = False
        self.clerk_status = 200
        self.generated: list[dict] = []
        self.stems_ready = True
        self.forbidden = False
        self.ids = ["clip-aaaa1", "clip-bbbb2"]
        self.songs_forbidden = False  # Songs too: Suno's state since October 2026.
        self.titles: dict[str, str] = {}
        self.durations: dict[str, float] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "auth.suno.com":
            assert request.headers["cookie"] == "__client=test"
            if self.clerk_status != 200:
                return httpx.Response(self.clerk_status)
            if url.path == "/v1/client":
                return httpx.Response(200, json={"response": {"last_active_session_id": "sess"}})
            return httpx.Response(200, json={"jwt": self.jwt})
        if url.host == "cdn1.suno.ai":
            assert "authorization" not in request.headers
            return httpx.Response(200, content=b"ID3 test audio")
        assert request.headers["authorization"] == f"Bearer {self.jwt}"
        if url.path == "/api/c/check":
            return httpx.Response(200, json={"required": self.captcha})
        if url.path == "/api/billing/info/":
            return httpx.Response(200, json={"total_credits_left": 2400})
        if url.path == "/api/generate/v2-web/":
            self.generated.append(json.loads(request.content))
            return httpx.Response(200, json={"clips": [{"id": clip_id} for clip_id in self.ids]})
        if url.path == "/api/clip/song-1/stems/pages":
            return httpx.Response(200, json={"pages": 2 if self.stems_ready else 0})
        if url.path == "/api/clip/song-1/stems":
            page = int(url.params.get("page", 0))
            if page > 1:
                return httpx.Response(400, json={"detail": "bad page"})
            stems = []
            for name in ("Vocals", "Backing_Vocals", "Drums", "Bass"):
                audio = (
                    "https://studio-api.prod.suno.com/api/forbidden"
                    if self.forbidden
                    else f"https://cdn1.suno.ai/stem-{page}-{name}.mp3"
                )
                stems.append(
                    {
                        "id": f"stem{page}-{name.lower()}",
                        "status": "complete",
                        "title": f"JUJU B ({name.replace('_', ' ')})",
                        "audio_url": audio,
                        "model_name": "chirp-haddock",
                        "metadata": {
                            "stem_type_group_name": name,
                            "stem_task": "twelve",
                            "stem_from_id": "song-1",
                        },
                    }
                )
            return httpx.Response(200, json={"stems": stems, "current_page": page})
        if url.path == "/api/gen/song-1/downbeats":
            beats = [[round(0.0422 + i * 0.764, 4), float(i % 4 + 1)] for i in range(16)]
            return httpx.Response(
                200,
                json={"state": "complete", "downbeats": beats, "downbeat_presence_confidence": 1.0},
            )
        if url.path == "/api/feed/v2":
            self.polls += 1
            done = self.polls >= 3
            served = "https://studio-api.prod.suno.com/api/forbidden" if self.songs_forbidden else None
            clips = [
                {
                    "id": clip_id,
                    "status": "complete" if done else "streaming",
                    "title": self.titles.get(clip_id, "Night Drive"),
                    "audio_url": (served or f"https://cdn1.suno.ai/{clip_id}.mp3") if done else "",
                    "metadata": {"tags": "synthwave", "duration": self.durations.get(clip_id)},
                }
                for clip_id in url.params["ids"].split(",")
            ]
            return httpx.Response(200, json={"clips": clips})
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNO_COOKIE", "__client=test")
    monkeypatch.setenv("SKITZ_SUNO_COOKIE_FILE", str(tmp_path / "cookie"))
    # Never touch the real ledger, inbox or ~/Downloads.
    monkeypatch.setenv("SKITZ_SUNO_HOME", str(tmp_path / "suno-home"))
    monkeypatch.setenv("SKITZ_SUNO_WATCH", str(tmp_path / "Downloads"))
    monkeypatch.setattr(suno.time, "sleep", lambda seconds: None)
    return FakeSuno()


def run(fake, capsys, *argv):
    code = suno_cli.main(list(argv), httpx.MockTransport(fake))
    return code, json.loads(capsys.readouterr().out)


def test_generate_waits_downloads_and_records_manifest(fake, capsys, tmp_path):
    out = tmp_path / "songs"
    code, result = run(
        fake,
        capsys,
        "generate",
        "--title",
        "Night Drive",
        "-t",
        "synthwave",
        "-l",
        "[Verse] neon",
        "-m",
        "v5",
        "--out",
        str(out),
    )
    assert code == 0, result
    assert fake.generated == [
        {
            "mv": "chirp-crow",
            "make_instrumental": False,
            "generation_type": "TEXT",
            "token": None,
            "prompt": "[Verse] neon",
            "tags": "synthwave",
            "title": "Night Drive",
        }
    ]
    assert [f["clip_id"] for f in result["files"]] == ["clip-aaaa1", "clip-bbbb2"]
    assert all(
        (out / f"Night-Drive-{i}.mp3").read_bytes() == b"ID3 test audio"
        for i in ("clip-aaa", "clip-bbb")
    )
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["request"]["title"] == "Night Drive"
    assert manifest["files"][0]["sha256"] == result["files"][0]["sha256"]


def test_bpm_goes_into_the_prompt_and_the_manifest(fake, capsys, tmp_path):
    out = tmp_path / "drums"
    code, result = run(
        fake, capsys, "generate", "-i", "-t", "boom bap drums", "--bpm", "90", "--out", str(out)
    )
    assert code == 0, result
    assert fake.generated[0]["tags"] == "boom bap drums, 90 bpm"
    assert "skitz_bpm" not in fake.generated[0]
    assert json.loads((out / "manifest.json").read_text())["request"]["skitz_bpm"] == 90


def test_stems_list_both_variants_with_readable_names(fake, capsys):
    code, result = run(fake, capsys, "stems", "song-1")
    assert code == 0, result
    assert result["variants"] == 2 and result["variant"] == 1
    assert [s["stem"] for s in result["stems"]] == ["Vocals", "Backing Vocals", "Drums", "Bass"]
    code, result = run(fake, capsys, "stems", "song-1", "--variant", "2")
    assert result["stems"][0]["id"] == "stem1-vocals"


def test_stems_download_selected_parts(fake, capsys, tmp_path):
    out = tmp_path / "stems"
    code, result = run(fake, capsys, "stems", "song-1", "--only", "drums", "bass", "-o", str(out))
    assert code == 0, result
    assert sorted(p.name for p in out.glob("*.mp3")) == ["Bass-stem0-ba.mp3", "Drums-stem0-dr.mp3"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["request"] == {"stem_from_id": "song-1", "variant": 1}


def test_forbidden_audio_is_reported_not_downloaded(fake, capsys, tmp_path):
    # Live Suno (October 2026) returns audio_url=/api/forbidden for stems and songs.
    fake.forbidden = True
    out = tmp_path / "stems"
    code, result = run(fake, capsys, "stems", "song-1", "-o", str(out))
    assert code == 7 and result["error_kind"] == "download_restricted"
    assert "Download on suno.com" in result["error"]
    assert not out.exists() or not list(out.glob("*.mp3"))
    code, result = run(fake, capsys, "stems", "song-1")
    assert code == 0 and result["stems"][0]["audio_url"] is None


def test_stems_not_made_yet_says_where_to_start_them(fake, capsys):
    fake.stems_ready = False
    code, result = run(fake, capsys, "stems", "song-1")
    assert code == 2 and result["error_kind"] == "not_ready"
    assert "Get Stems" in result["error"]


def test_downbeats_give_bpm_and_bar_offset(fake, capsys):
    code, result = run(fake, capsys, "downbeats", "song-1")
    assert code == 0
    assert result["bpm"] == pytest.approx(78.53, abs=0.05)
    assert result["first_downbeat"] == 0.0422
    assert result["confidence"] == 1.0


def test_captcha_stops_without_generating(fake, capsys):
    fake.captcha = True
    code, result = run(fake, capsys, "generate", "-d", "a song")
    assert code == 4
    assert result["error_kind"] == "captcha_required"
    assert fake.generated == []


def test_expired_session_and_missing_cookie(fake, capsys, monkeypatch):
    fake.clerk_status = 401
    code, result = run(fake, capsys, "whoami")
    assert (code, result["error_kind"]) == (3, "auth_expired")
    monkeypatch.delenv("SUNO_COOKIE")
    code, result = run(fake, capsys, "whoami")
    assert (code, result["error_kind"]) == (3, "auth_missing")


def test_login_saves_cookie_privately(fake, capsys, tmp_path):
    code, result = run(fake, capsys, "login", "__client=test")
    assert code == 0 and result["credits"] == 2400
    saved = tmp_path / "cookie"
    assert saved.read_text() == "__client=test"
    assert saved.stat().st_mode & 0o777 == 0o600


def test_wait_timeout_returns_ids_to_resume(fake, capsys):
    code, result = run(fake, capsys, "wait", "clip-aaaa1", "--timeout", "0")
    assert code == 6
    assert result["clips"][0]["id"] == "clip-aaaa1"


def test_service_confines_downloads_to_workspace(fake, tmp_path):
    service = suno.SunoService(tmp_path, httpx.MockTransport(fake))
    with pytest.raises(ValueError):
        service.suno_wait(["clip-aaaa1"], output_dir="../outside")
    result = service.suno_generate(description="lofi", output_dir="songs/lofi")
    assert result["status"] == "complete"
    assert (tmp_path / "songs/lofi/manifest.json").is_file()


def test_mcp_server_lists_suno_tools(tmp_path):
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "skitz_music.cli", "mcp", "--workspace", str(tmp_path)],
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert {
                    "suno_credits",
                    "suno_generate",
                    "suno_status",
                    "suno_wait",
                    "suno_lyrics",
                    "suno_stems",
                    "suno_downbeats",
                    "suno_download",
                    "suno_inbox",
                    "samples_info",
                    "samples_loops",
                    "samples_hits",
                    "samples_slice",
                    "samples_layer",
                    "play_audio",
                    "stop_audio",
                } <= names

    asyncio.run(check())


def test_downbeats_infer_the_meter():
    waltz = {"downbeats": [[0.5 * i, float(i % 3 + 1)] for i in range(12)]}
    assert suno.tempo_from_downbeats(waltz)["beats_per_bar"] == 3
    assert suno.tempo_from_downbeats(waltz)["bpm"] == 120.0
    four = {"downbeats": [[0.5 * i, float(i % 4 + 1)] for i in range(16)]}
    assert suno.tempo_from_downbeats(four)["beats_per_bar"] == 4


# --- downloads made on suno.com ---------------------------------------------------------

SONG_A = "2ef5b39a-d572-45da-8e6c-1a49e970b388"
SONG_B = "16b599c8-80b6-49a7-96d9-639462fe13a8"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def suno_download(path, clip_id=None, seconds=1.0, frequency=440):
    """A file like the ones Suno's Download button makes (id in the comment tag)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tag = ["-metadata", f"comment=made with suno; created=2026-10-17T21:25:36Z; id={clip_id}"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"sine=frequency={frequency}:duration={seconds}", *(tag if clip_id else []), str(path)],
        check=True,
    )  # fmt: skip
    return path


def forbidden_songs(fake, titles=None, durations=None):
    fake.songs_forbidden = True
    fake.polls = 10  # finished
    fake.titles.update(titles or {})
    fake.durations.update(durations or {})


@needs_ffmpeg
def test_downloads_are_matched_by_the_id_suno_embeds(fake, capsys, tmp_path):
    forbidden_songs(fake)  # Both clips are titled "Night Drive": only the id tells them apart.
    downloads = tmp_path / "Downloads"
    suno_download(downloads / "Night Drive.m4a", SONG_B, frequency=220)
    suno_download(downloads / "Night Drive (1).m4a", SONG_A, frequency=880)
    suno_download(downloads / "someone else.m4a")  # not a Suno file
    (downloads / "Night Drive.m4a.crdownload").write_bytes(b"partial")
    out = tmp_path / "songs"
    code, result = run(fake, capsys, "download", SONG_A, SONG_B, "--out", str(out))
    assert code == 0, result
    by_clip = {entry["clip_id"]: entry for entry in result["files"]}
    assert set(by_clip) == {SONG_A, SONG_B}
    for clip_id, entry in by_clip.items():
        assert suno_inbox.probe(Path(entry["path"]))["clip_id"] == clip_id
        assert entry["matched_by"] == "embedded_id" and entry["origin"] == "browser_download"
    assert Path(by_clip[SONG_A]["path"]).name == f"Night-Drive-{SONG_A[:8]}.m4a"
    assert (downloads / "Night Drive.m4a").is_file()  # The user's copy stays.
    manifest = json.loads((out / "manifest.json").read_text())
    assert {f["clip_id"] for f in manifest["files"]} == {SONG_A, SONG_B}


@needs_ffmpeg
def test_the_bpm_asked_for_reaches_imported_files(fake, capsys, tmp_path):
    fake.ids = [SONG_A, SONG_B]
    code, result = run(fake, capsys, "generate", "-i", "-t", "boom bap drums", "--bpm", "90")
    assert code == 0 and result["ids"] == [SONG_A, SONG_B]
    forbidden_songs(fake)
    suno_download(tmp_path / "Downloads" / "Boom Bap.m4a", SONG_A)
    out = tmp_path / "drums"
    code, result = run(fake, capsys, "download", SONG_A, "--out", str(out))
    assert code == 0, result
    imported = Path(result["files"][0]["path"])
    assert result["files"][0]["request"]["skitz_bpm"] == 90
    assert samples.suno_bpm(imported) == 90


@needs_ffmpeg
def test_missing_downloads_point_to_the_song_pages(fake, capsys, tmp_path):
    forbidden_songs(fake)
    suno_download(tmp_path / "Downloads" / "Night Drive.m4a", SONG_A)
    code, result = run(fake, capsys, "download", SONG_A, SONG_B, "--out", str(tmp_path / "songs"))
    assert code == 7 and result["error_kind"] == "download_restricted"
    assert result["missing"] == [SONG_B]
    assert result["song_urls"] == [f"https://suno.com/song/{SONG_B}"]
    assert [f["clip_id"] for f in result["files"]] == [SONG_A]  # What was there is kept.


@needs_ffmpeg
def test_wait_for_browser_opens_the_page_and_takes_the_click(fake, capsys, tmp_path, monkeypatch):
    forbidden_songs(fake)
    opened = []
    monkeypatch.setattr(suno_inbox.webbrowser, "open", opened.append)
    clicks = iter([None, lambda: suno_download(tmp_path / "Downloads" / "x.m4a", SONG_A)])

    def sleep(seconds):
        click = next(clicks, None)
        if click:
            click()

    monkeypatch.setattr(suno_inbox.time, "sleep", sleep)
    out = tmp_path / "songs"
    code, result = run(fake, capsys, "download", SONG_A, "--out", str(out), "--wait-for-browser")
    assert code == 0, result
    assert opened == [f"https://suno.com/song/{SONG_A}"]
    assert result["files"][0]["clip_id"] == SONG_A


@needs_ffmpeg
def test_untagged_files_match_by_title_and_length_only_when_unambiguous(tmp_path):
    wav = suno_download(tmp_path / "Night Drive.wav", seconds=2.0)
    found = suno_inbox.scan([tmp_path])
    one = [{"id": SONG_A, "title": "Night Drive", "metadata": {"duration": 2.0}},
           {"id": SONG_B, "title": "Other Song", "metadata": {"duration": 2.0}}]  # fmt: skip
    assert suno_inbox.match(one, found)[SONG_A]["path"] == wav
    two = [{"id": SONG_A, "title": "Night Drive", "metadata": {"duration": 2.0}},
           {"id": SONG_B, "title": "Night Drive", "metadata": {"duration": 2.1}}]  # fmt: skip
    assert suno_inbox.match(two, found) == {}  # Two clips fit: don't guess.
    longer = [{"id": SONG_A, "title": "Night Drive", "metadata": {"duration": 9.0}}]
    assert suno_inbox.match(longer, found) == {}


@needs_ffmpeg
def test_imports_keep_earlier_manifest_entries_and_inbox_lists_files(fake, capsys, tmp_path):
    forbidden_songs(fake)
    out = tmp_path / "songs"
    suno_download(tmp_path / "Downloads" / "a.m4a", SONG_A)
    assert run(fake, capsys, "download", SONG_A, "--out", str(out))[0] == 0
    suno_download(tmp_path / "Downloads" / "b.m4a", SONG_B)
    assert run(fake, capsys, "download", SONG_B, "--out", str(out))[0] == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert {f["clip_id"] for f in manifest["files"]} == {SONG_A, SONG_B}
    code, listing = run(fake, capsys, "inbox")
    assert code == 0
    assert {d["clip_id"] for d in listing["downloads"]} == {SONG_A, SONG_B}


@needs_ffmpeg
def test_older_folder_manifests_keep_their_own_bpm(fake, tmp_path):
    forbidden_songs(fake)
    out = tmp_path / "songs"
    old = suno_download(out / "Old-Song-11111111.m4a", seconds=0.5)
    (out / "manifest.json").write_text(json.dumps({  # the pre-merge format: one request per folder
        "source": "suno", "request": {"skitz_bpm": 120}, "clips": [],
        "files": [{"clip_id": "11111111-old", "path": str(old), "sha256": suno_inbox.sha256(old)}],
    }))  # fmt: skip
    suno_download(tmp_path / "Downloads" / "new.m4a", SONG_A)
    client = suno.SunoClient(transport=httpx.MockTransport(fake))
    result = client.download(client.feed([SONG_A]), out, request={"skitz_bpm": 90})
    assert result["files"][0]["request"] == {"skitz_bpm": 90}  # explicit request wins
    assert samples.suno_bpm(old) == 120
    assert samples.suno_bpm(Path(result["files"][0]["path"])) == 90


@needs_ffmpeg
def test_rerunning_a_download_reuses_files_already_imported(fake, capsys, tmp_path, monkeypatch):
    forbidden_songs(fake)
    original = suno_download(tmp_path / "Downloads" / "a.m4a", SONG_A)
    out = tmp_path / "songs"
    assert run(fake, capsys, "download", SONG_A, "--out", str(out))[0] == 0
    original.unlink()  # The user tidies ~/Downloads.
    opened = []
    monkeypatch.setattr(suno_inbox.webbrowser, "open", opened.append)
    code, result = run(fake, capsys, "download", SONG_A, "--out", str(out), "--wait-for-browser")
    assert code == 0, result
    assert [f["clip_id"] for f in result["files"]] == [SONG_A] and opened == []
