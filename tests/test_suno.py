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
from skitz_music import (
    browser_login,
    mcp_server,
    samples,
    suno,
    suno_budget,
    suno_cli,
    suno_inbox,
    suno_jobs,
)


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
        self.cookies = {"__client=test"}  # Sessions Clerk accepts.
        self.profile_cookie: str | None = None  # What the Skitz Chrome profile holds.
        self.credits = 2400
        self.cost = 10  # Credits Suno takes per generation.
        self.captcha_checks = 0
        self.captcha_clears_after: int | None = None  # A person solved it on suno.com.
        self.library: list[dict] = []
        self.pages: list[int] = []
        # Failures to return first, by path: a status code, (status, headers) or exception.
        self.failures: dict[str, list] = {}
        self.calls: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.calls[url.path] = self.calls.get(url.path, 0) + 1
        queued = self.failures.get(url.path)
        if queued:
            failure = queued.pop(0)
            if isinstance(failure, Exception):
                raise failure
            status, headers = failure if isinstance(failure, tuple) else (failure, {})
            return httpx.Response(status, headers=headers, text="upstream trouble")
        if url.host == "auth.suno.com":
            if request.headers["cookie"] not in self.cookies:
                return httpx.Response(401)
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
            self.captcha_checks += 1
            if self.captcha_clears_after and self.captcha_checks > self.captcha_clears_after:
                self.captcha = False
            return httpx.Response(200, json={"required": self.captcha})
        if url.path == "/api/billing/info/":
            return httpx.Response(200, json={"total_credits_left": self.credits})
        if url.path == "/api/generate/v2-web/":
            self.generated.append(json.loads(request.content))
            self.credits -= self.cost
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
        if url.path == "/api/feed/v2" and "page" in url.params:
            page = int(url.params["page"])
            self.pages.append(page)
            clips = self.library[page * 20 : page * 20 + 20]
            more = len(self.library) > page * 20 + 20
            return httpx.Response(200, json={"clips": clips, "current_page": page, "has_more": more})
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
    fake = FakeSuno()
    fake.refreshes = 0

    def refresh_cookie():  # Never start a real Chrome.
        fake.refreshes += 1
        return fake.profile_cookie

    monkeypatch.setattr(browser_login, "refresh_cookie", refresh_cookie)
    return fake


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
                    "suno_library",
                    "suno_jobs",
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


# --- retries ------------------------------------------------------------------------------


@pytest.fixture
def sleeps(monkeypatch):
    waited: list[float] = []
    monkeypatch.setattr(suno.time, "sleep", waited.append)
    return waited


def test_transient_errors_are_retried_with_backoff_and_retry_after(fake, capsys, sleeps):
    fake.failures["/api/billing/info/"] = [(503, {"Retry-After": "7"}), 429]
    code, result = run(fake, capsys, "whoami")
    assert code == 0 and result["credits"] == 2400
    assert fake.calls["/api/billing/info/"] == 3
    assert 7 <= sleeps[0] <= 8  # Retry-After, plus up to 1 s of jitter
    assert 2 <= sleeps[1] <= 3  # Second backoff step


def test_retries_stop_after_three_tries(fake, capsys, sleeps):
    fake.failures["/api/billing/info/"] = [502, 504, 503, 503]
    code, result = run(fake, capsys, "whoami")
    assert (code, result["error_kind"], result["http_status"]) == (2, "api_error", 503)
    assert fake.calls["/api/billing/info/"] == 3 and len(sleeps) == 2


def test_network_errors_are_retried(fake, capsys, sleeps):
    fake.failures["/api/feed/v2"] = [httpx.ReadTimeout("slow"), httpx.ConnectError("down")]
    code, result = run(fake, capsys, "status", "clip-aaaa1")
    assert code == 0 and result["clips"][0]["id"] == "clip-aaaa1"
    assert len(sleeps) == 2


def test_a_long_retry_after_is_reported_not_waited_out(fake, capsys, sleeps):
    fake.failures["/api/billing/info/"] = [(429, {"Retry-After": "3600"})]
    code, result = run(fake, capsys, "whoami")
    assert code == 2 and result["retry_after"] == 3600 and sleeps == []


def test_generation_is_retried_only_when_suno_surely_did_not_take_it(fake, capsys, sleeps):
    path = "/api/generate/v2-web/"
    fake.failures[path] = [503]  # Unavailable: nothing was started, so try again.
    assert run(fake, capsys, "generate", "-d", "a song")[0] == 0
    assert fake.calls[path] == 2 and len(fake.generated) == 1
    fake.failures[path] = [504]  # Gateway timeout: it may have gone through.
    code, result = run(fake, capsys, "generate", "-d", "a song")
    assert (code, result["error_kind"]) == (2, "api_error")
    assert "skitz suno library" in result["error"]
    assert fake.calls[path] == 3
    fake.failures[path] = [httpx.ReadTimeout("no answer")]
    code, result = run(fake, capsys, "generate", "-d", "a song")
    assert (code, result["error_kind"]) == (2, "network_error")
    assert fake.calls[path] == 4


# --- library ------------------------------------------------------------------------------


def library_song(index: int, title: str | None = None) -> dict:
    return {
        "id": f"lib-{index:04d}",
        "status": "complete",
        "title": title or f"Song {index}",
        "audio_url": "https://studio-api.prod.suno.com/api/forbidden",
        "created_at": f"2026-10-{17 - index // 20:02d}T12:00:00Z",
        "metadata": {"tags": "lofi, rain" if index % 2 else "synthwave", "duration": 120.0},
    }


def test_library_search_pages_through_and_marks_downloads(fake, capsys, monkeypatch, tmp_path):
    fake.library = [library_song(i) for i in range(45)]
    fake.library[33] = library_song(33, "JUJU B (Remastered)")
    # Suno's feed also holds stems made on suno.com, and the trash.
    fake.library[3] = library_song(3, "JUJU B (Remastered) (Vocals)")
    fake.library[3]["metadata"]["stem_from_id"] = "lib-0033"
    fake.library[4] = {**library_song(4, "JUJU B (Remastered)"), "is_trashed": True}
    monkeypatch.setattr(
        suno_inbox,
        "scan",
        lambda dirs=None: [{"clip_id": "lib-0033", "path": tmp_path / "x.m4a", "duration": 120}],
    )
    code, result = run(fake, capsys, "library", "--search", "juju b (remastered)")
    assert code == 0, result
    assert fake.pages == [0, 1, 2]  # Stops at the short last page.
    [song] = result["songs"]
    assert song["title"] == "JUJU B (Remastered)" and song["downloaded"] is True
    assert song["audio_url"] is None and song["song_url"].endswith("/song/lib-0033")

    code, result = run(fake, capsys, "library", "-s", "JUJU B", "--stems")
    assert [s["id"] for s in result["songs"]] == ["lib-0003", "lib-0033"]
    assert result["songs"][0]["stem_from_id"] == "lib-0033"

    fake.pages.clear()
    code, result = run(fake, capsys, "library", "--limit", "25")
    assert fake.pages == [0, 1] and result["count"] == 25
    assert [s["downloaded"] for s in result["songs"]].count(True) == 0
    code, result = run(fake, capsys, "library", "-s", "SYNTHWAVE", "-n", "3")
    assert [s["id"] for s in result["songs"]] == ["lib-0000", "lib-0002", "lib-0006"]
    fake.pages.clear()
    code, result = run(fake, capsys, "library", "-s", "juju", "--pages", "1")
    assert result["songs"] == [] and fake.pages == [0]


# --- jobs ---------------------------------------------------------------------------------


def test_jobs_survive_a_restart_and_resume_into_their_folder(fake, capsys, tmp_path):
    out = tmp_path / "songs"
    code, result = run(
        fake, capsys, "generate", "-d", "night drive", "--out", str(out), "--timeout", "0"
    )
    assert code == 6  # Suno wasn't done; the process could exit here.
    saved = json.loads((tmp_path / "suno-home/jobs.json").read_text())["jobs"]
    assert saved[0]["ids"] == ["clip-aaaa1", "clip-bbbb2"]
    assert saved[0]["output_dir"] == str(out.resolve())
    assert saved[0]["request"]["gpt_description_prompt"] == "night drive"

    code, listing = run(fake, capsys, "jobs")
    assert code == 0 and listing["open"] == 1
    assert [c["status"] for c in listing["jobs"][0]["clips"]] == ["streaming", "streaming"]

    code, resumed = run(fake, capsys, "jobs", "--resume")
    assert code == 0, resumed
    [job] = resumed["jobs"]
    assert job["state"] == "done" and all(c["saved_to"] for c in job["clips"])
    names = sorted(p.name for p in out.glob("*.mp3"))
    assert names == ["Night-Drive-clip-aaa.mp3", "Night-Drive-clip-bbb.mp3"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["request"]["gpt_description_prompt"] == "night drive"
    assert run(fake, capsys, "jobs")[1]["jobs"] == []
    assert run(fake, capsys, "jobs", "--all")[1]["jobs"][0]["state"] == "done"


def test_finished_generations_close_their_job(fake, capsys, tmp_path):
    code, _ = run(fake, capsys, "generate", "-d", "x", "--out", str(tmp_path / "a"))
    assert code == 0
    code, _ = run(fake, capsys, "generate", "-d", "y", "--wait")  # no folder asked for
    assert code == 0
    states = [job["state"] for job in suno_jobs.load()]
    assert states == ["done", "complete"]


def test_jobs_can_be_dismissed(fake, capsys):
    code, result = run(fake, capsys, "generate", "-d", "x")
    assert code == 0 and result["job"] == "clip-aaaa1"
    assert run(fake, capsys, "jobs", "--dismiss", "clip-bbbb2")[1]["status"] == "dismissed"
    assert run(fake, capsys, "jobs")[1]["jobs"] == []
    code, result = run(fake, capsys, "jobs", "--dismiss", "nope")
    assert (code, result["error_kind"]) == (1, "usage")


@needs_ffmpeg
def test_resume_imports_browser_downloads_when_they_arrive(fake, capsys, tmp_path):
    fake.ids = [SONG_A, SONG_B]
    forbidden_songs(fake)
    out = tmp_path / "songs"
    code, result = run(fake, capsys, "generate", "-t", "lofi", "-l", "x", "--out", str(out))
    assert code == 7 and result["missing"] == [SONG_A, SONG_B]
    assert suno_jobs.load()[0]["state"] == "needs_download"

    suno_download(tmp_path / "Downloads" / "a.m4a", SONG_A)
    code, result = run(fake, capsys, "jobs", "--resume")
    assert (code, result["error_kind"]) == (7, "download_restricted")
    assert result["song_urls"] == [f"https://suno.com/song/{SONG_B}"]
    [job] = result["jobs"]
    assert job["state"] == "needs_download" and job["missing"] == [SONG_B]
    assert [c["downloaded"] for c in job["clips"]] == [True, False]

    suno_download(tmp_path / "Downloads" / "b.m4a", SONG_B)
    code, result = run(fake, capsys, "jobs", "--resume")
    assert code == 0 and result["jobs"][0]["state"] == "done"
    assert len(json.loads((out / "manifest.json").read_text())["files"]) == 2


def test_mcp_resume_stays_inside_the_workspace(fake, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = suno.SunoClient(transport=httpx.MockTransport(fake))
    client.generate(suno.build_payload("elsewhere"), output_dir=tmp_path / "outside")
    fake.ids = ["clip-cccc3", "clip-dddd4"]
    service = suno.SunoService(workspace, httpx.MockTransport(fake))
    service.suno_generate(description="inside", output_dir="songs")
    assert [job["state"] for job in suno_jobs.load()] == ["submitted", "done"]
    result = service.suno_jobs(resume=True)
    [job] = result["jobs"]
    assert job["state"] == "needs_download" and "outside the workspace" in job["skipped"]
    assert not (tmp_path / "outside").exists()


# --- budget -------------------------------------------------------------------------------


def test_budget_lets_generations_through_until_the_next_would_pass_it(fake, capsys, tmp_path):
    assert run(fake, capsys, "budget", "set", "25")[1]["daily_limit"] == 25
    assert run(fake, capsys, "generate", "-d", "one")[0] == 0
    assert run(fake, capsys, "generate", "-d", "two")[0] == 0
    code, result = run(fake, capsys, "generate", "-d", "three")
    assert (code, result["error_kind"]) == (8, "budget_exceeded")
    assert len(fake.generated) == 2  # Refused before anything was sent.
    assert result["budget"] == {**result["budget"], "spent_today": 20, "remaining": 5}
    ledger = [json.loads(line) for line in (tmp_path / "suno-home/spend.jsonl").open()]
    assert [(e["credits_before"], e["credits_after"], e["spent"]) for e in ledger] == [
        (2400, 2390, 10),
        (2390, 2380, 10),
    ]
    assert ledger[0]["ids"] == ["clip-aaaa1", "clip-bbbb2"] and not ledger[0]["estimated"]
    assert run(fake, capsys, "whoami")[1]["budget"]["remaining"] == 5
    assert run(fake, capsys, "budget", "clear")[1]["daily_limit"] is None
    assert run(fake, capsys, "generate", "-d", "three")[0] == 0


def test_budget_from_the_environment_wins_and_dry_run_shows_it(fake, capsys, monkeypatch):
    run(fake, capsys, "budget", "set", "100")
    monkeypatch.setenv("SKITZ_SUNO_BUDGET", "5")
    code, result = run(fake, capsys, "generate", "-d", "x", "--dry-run")
    assert (code, result["error_kind"]) == (8, "budget_exceeded")
    assert result["budget"]["source"] == "env" and result["budget"]["next_cost"] == 10
    monkeypatch.setenv("SKITZ_SUNO_BUDGET", "lots")
    assert run(fake, capsys, "generate", "-d", "x")[1]["error_kind"] == "usage"
    assert fake.generated == []


def test_unmeasured_spending_counts_the_expected_cost(fake, capsys):
    fake.cost = 0  # Suno hadn't deducted yet when Skitz looked.
    assert run(fake, capsys, "generate", "-d", "x")[0] == 0
    [entry] = suno_budget.entries()
    assert entry["spent"] == suno_budget.DEFAULT_COST and entry["estimated"]


def test_only_todays_spending_counts(fake, capsys, tmp_path):
    ledger = tmp_path / "suno-home/spend.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"day": "2026-01-01", "spent": 15, "model": "chirp-crow"}) + "\n")
    run(fake, capsys, "budget", "set", "20")
    status = suno_budget.status("chirp-hawk")
    assert status["spent_today"] == 0 and status["next_cost"] == 15  # Last measured cost
    assert run(fake, capsys, "generate", "-d", "x")[0] == 0
    status = suno_budget.status("chirp-hawk")
    assert status["spent_today"] == 10 and status["next_cost"] == 10  # Same model wins
    assert run(fake, capsys, "generate", "-d", "x")[0] == 0
    assert run(fake, capsys, "generate", "-d", "x")[0] == 8


def test_mcp_tools_report_suno_errors_to_the_model():
    def refused():
        raise suno.SunoError("budget_exceeded", "Ask first.", budget={"remaining": 0})

    with pytest.raises(mcp_server.ToolError) as caught:
        mcp_server.reported(refused)()
    report = json.loads(str(caught.value))
    assert report["error_kind"] == "budget_exceeded" and report["budget"]["remaining"] == 0


# --- reconnect ----------------------------------------------------------------------------


def test_expired_session_reconnects_from_the_skitz_profile(fake, capsys, tmp_path):
    fake.cookies = {"__client=fresh"}  # The saved session no longer works...
    fake.profile_cookie = "__client=fresh"  # ...but the Skitz Chrome profile has a new one.
    code, result = run(fake, capsys, "whoami")
    assert code == 0 and result["credits"] == 2400 and fake.refreshes == 1
    saved = tmp_path / "cookie"
    assert saved.read_text() == "__client=fresh" and saved.stat().st_mode & 0o777 == 0o600


def test_reconnect_gives_up_after_one_try(fake, capsys, tmp_path):
    fake.cookies = set()
    fake.profile_cookie = "__client=also-stale"
    code, result = run(fake, capsys, "whoami")
    assert (code, result["error_kind"]) == (3, "auth_expired") and fake.refreshes == 1
    assert not (tmp_path / "cookie").exists()
    fake.profile_cookie = None
    assert run(fake, capsys, "whoami")[0] == 3 and fake.refreshes == 2


def test_a_cookie_being_checked_is_never_swapped(fake, capsys):
    fake.profile_cookie = "__client=test"
    code, result = run(fake, capsys, "login", "__client=wrong")
    assert code == 3 and fake.refreshes == 0


def test_refresh_reads_only_the_skitz_profile(monkeypatch, tmp_path):
    reads = []
    monkeypatch.setattr(browser_login, "find_chrome", lambda: "/fake/chrome")
    monkeypatch.setattr(
        browser_login,
        "read_auth_cookies",
        lambda chrome, profile: reads.append(profile) or "__client=fresh",
    )
    assert browser_login.refresh_cookie() is None  # No Skitz profile yet: nothing to read.
    profile = tmp_path / "suno-home/browser"
    profile.mkdir(parents=True)
    assert browser_login.refresh_cookie() == "__client=fresh" and reads == [profile]

    monkeypatch.setenv("HOME", str(tmp_path))
    everyday = tmp_path / "Library/Application Support/Google/Chrome"
    everyday.mkdir(parents=True)
    monkeypatch.setenv("SKITZ_SUNO_BROWSER_PROFILE", str(everyday / "Default"))
    assert browser_login.is_everyday_profile(everyday / "Default")
    assert browser_login.refresh_cookie() is None and reads == [profile]
    with pytest.raises(RuntimeError, match="everyday browser"):
        browser_login.wait_for_login(lambda header: {}, chrome="/fake/chrome")


# --- captcha handoff ----------------------------------------------------------------------


def test_wait_for_captcha_hands_off_to_the_person_then_retries_once(fake, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr(suno.webbrowser, "open", opened.append)
    fake.captcha = True
    fake.captcha_clears_after = 3  # Solved on suno.com while Skitz polls.
    code, result = run(fake, capsys, "generate", "-d", "a song", "--wait-for-captcha")
    assert code == 0, result
    assert opened == ["https://suno.com/create"]
    assert len(fake.generated) == 1 and fake.captcha_checks == 5


def test_wait_for_captcha_gives_up_without_generating(fake, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr(suno.webbrowser, "open", opened.append)
    fake.captcha = True
    code, result = run(
        fake, capsys, "generate", "-d", "a", "--wait-for-captcha", "--captcha-timeout", "0"
    )
    assert (code, result["error_kind"]) == (4, "captcha_required")
    assert opened == ["https://suno.com/create"] and fake.generated == []
    code, result = run(fake, capsys, "generate", "-d", "a")  # Without the flag: no browser.
    assert code == 4 and len(opened) == 1
