import json
import sys

import httpx
import pytest
from skitz_music import auth_cli, cli, suno

VALID = "eyJhbGciOiJSUzI1NiJ9.client-cookie-value.signature"


def fake_suno(request: httpx.Request) -> httpx.Response:
    """Clerk accepts only the VALID __client cookie; billing reports a Pro plan."""
    if request.url.host == "auth.suno.com":
        if request.headers.get("cookie") != f"__client={VALID}":
            return httpx.Response(200, json={"response": {"sessions": []}})
        if request.url.path == "/v1/client":
            return httpx.Response(200, json={"response": {"last_active_session_id": "sess"}})
        return httpx.Response(200, json={"jwt": "a.eyJleHAiOjQxMDI0NDQ4MDB9.b"})
    if request.url.path == "/api/billing/info/":
        return httpx.Response(200, json={"total_credits_left": 2440, "plan": {"name": "Pro Plan"}})
    return httpx.Response(404)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SKITZ_SUNO_COOKIE_FILE", str(tmp_path / "suno/cookie"))
    monkeypatch.delenv("SUNO_COOKIE", raising=False)
    monkeypatch.delenv("SUNO_JWT", raising=False)
    monkeypatch.setattr(
        auth_cli, "chatgpt_status", lambda: {"provider": "chatgpt", "connected": True}
    )
    return tmp_path


T = httpx.MockTransport(fake_suno)


@pytest.mark.parametrize(
    "pasted",
    [VALID, f"__client={VALID}", f"cookie: __client_uat=1; __client={VALID}; x=y", f' "{VALID}" '],
)
def test_any_reasonable_paste_becomes_the_client_cookie(pasted):
    assert auth_cli.normalize_suno_cookie(pasted) == f"__client={VALID}"


@pytest.mark.parametrize(
    ("pasted", "hint"),
    [
        ('{"response": {"object": "client"}}', "page text"),
        ("__client_uat=1790219982; other=1", "found: __client_uat, other"),
        ("not-a-cookie", "doesn't look like"),
        ("   ", "Nothing was pasted"),
    ],
)
def test_wrong_pastes_explain_what_went_wrong(pasted, hint):
    with pytest.raises(ValueError, match=hint):
        auth_cli.normalize_suno_cookie(pasted)


def test_login_with_value_checks_and_saves_privately(home):
    result = auth_cli.login_suno(VALID, T)
    assert result["plan"] == "Pro Plan" and result["credits"] == 2440
    saved = home / "suno/cookie"
    assert saved.read_text() == f"__client={VALID}"
    assert saved.stat().st_mode & 0o777 == 0o600


def test_guided_login_opens_pages_and_retries(home, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter(["", "__client_uat=1", VALID])
    opened = []
    result = auth_cli.login_suno(None, T, prompt=lambda _: next(answers), open_url=opened.append)
    assert result["status"] == "connected"
    assert opened == [auth_cli.SUNO_SIGN_IN, auth_cli.SUNO_COOKIE_PAGE]


def test_guided_login_gives_up_after_three_tries(home, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter(["", "short", "short", "short"])
    with pytest.raises(suno.SunoError) as error:
        auth_cli.login_suno(None, T, prompt=lambda _: next(answers), open_url=lambda _: None)
    assert error.value.kind == "auth_missing"
    assert not (home / "suno/cookie").exists()


def test_rejected_session_is_not_saved(home):
    with pytest.raises(suno.SunoError, match="while signed in"):
        auth_cli.login_suno("x" * 40, T)
    assert not (home / "suno/cookie").exists()


def test_auth_list_login_logout(home, capsys):
    assert auth_cli.main(["--json", "list"], T) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0] == {**rows[0], "provider": "suno", "connected": False}
    assert auth_cli.main(["--json", "login", "suno", "--value", VALID], T) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "connected"
    assert auth_cli.main(["list"], T) == 0
    assert "suno     connected" in capsys.readouterr().out
    assert auth_cli.main(["logout", "suno"], T) == 0
    assert "logged out" in capsys.readouterr().out
    assert not (home / "suno/cookie").exists()


def test_skitz_login_suno_shortcut(home, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(auth_cli, "main", lambda argv, transport=None: calls.append(argv) or 0)
    monkeypatch.setattr(sys, "argv", ["skitz", "login", "suno", "--value", "x"])
    assert cli.main() == 0
    monkeypatch.setattr(sys, "argv", ["skitz", "auth", "logout", "suno"])
    assert cli.main() == 0
    assert calls == [["login", "suno", "--value", "x"], ["logout", "suno"]]
