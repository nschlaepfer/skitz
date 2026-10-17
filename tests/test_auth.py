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
        ('{"response": {"object": "client"}}', "doesn't include your login"),
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


def page(client: str | None) -> str:
    """A copy of auth.suno.com/v1/client, with the login embedded right after sign-in."""
    url = f"https://auth.suno.com/social/login/?next=x&__client={client}" if client else ""
    return json.dumps(
        {
            "response": {
                "sign_in": {
                    "first_factor_verification": {"external_verification_redirect_url": url}
                },
                "last_active_token": {"jwt": "eyJ.access.token"},
            }
        }
    )


def watch(clipboard_values, **kwargs):
    values = iter(clipboard_values)
    last = [""]

    def clipboard():
        last[0] = next(values, last[0])
        return last[0]

    opened = []
    kwargs.setdefault("timeout", 2)  # never let a failing test wait out the real timeout
    result = auth_cli.login_suno(
        None, T, open_url=opened.append, clipboard=clipboard, sleep=lambda _: None, **kwargs
    )
    return result, opened


def test_copying_the_page_connects_without_any_typing(home, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    result, opened = watch(["some unrelated text", page(None), page(VALID)])
    assert result["status"] == "connected" and result["plan"] == "Pro Plan"
    assert opened == [auth_cli.SUNO_COOKIE_PAGE]
    assert (home / "suno/cookie").read_text() == f"__client={VALID}"
    err = capsys.readouterr().err
    assert "Cmd-A then Cmd-C" in err
    assert "doesn't include your login" in err  # the copy without the embedded login
    assert "unrelated" not in err  # other clipboard contents are ignored silently


def test_copying_the_cookie_value_from_devtools_also_works(home, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    result, _ = watch([VALID])
    assert result["status"] == "connected"


def test_a_rejected_login_keeps_waiting_for_a_good_one(home, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    result, _ = watch([page("eyJ" + "x" * 40), page(VALID)])
    assert result["status"] == "connected"
    assert "sign back in" in capsys.readouterr().err


def test_watching_gives_up_after_the_timeout(home, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(suno.SunoError) as error:
        watch([""], timeout=0.05)
    assert error.value.kind == "auth_missing"
    assert not (home / "suno/cookie").exists()


def test_rejected_session_is_not_saved(home):
    with pytest.raises(suno.SunoError, match="sign back in"):
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


def test_whole_page_copy_yields_the_embedded_client():
    assert auth_cli.normalize_suno_cookie(page(VALID)) == f"__client={VALID}"
