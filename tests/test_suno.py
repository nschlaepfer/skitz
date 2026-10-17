import asyncio
import base64
import json
import sys
import time

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from skitz_music import suno, suno_cli


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

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "clerk.suno.com":
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
            return httpx.Response(200, json={"clips": [{"id": "clip-aaaa1"}, {"id": "clip-bbbb2"}]})
        if url.path == "/api/feed/v2":
            self.polls += 1
            done = self.polls >= 3
            clips = [
                {
                    "id": clip_id,
                    "status": "complete" if done else "streaming",
                    "title": "Night Drive",
                    "audio_url": f"https://cdn1.suno.ai/{clip_id}.mp3" if done else "",
                    "metadata": {"tags": "synthwave"},
                }
                for clip_id in url.params["ids"].split(",")
            ]
            return httpx.Response(200, json={"clips": clips})
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNO_COOKIE", "__client=test")
    monkeypatch.setenv("SKITZ_SUNO_COOKIE_FILE", str(tmp_path / "cookie"))
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
                    "samples_info",
                    "samples_loops",
                    "samples_hits",
                    "samples_slice",
                    "samples_layer",
                } <= names

    asyncio.run(check())
