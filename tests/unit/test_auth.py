from unittest.mock import patch, MagicMock

import pytest
import requests

from pyrchidekt import api


def _response(status, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    return r


def test_login_sets_jwt_header():
    body = {"access_token": "abc", "refresh_token": "def", "user": {"id": 1}}
    with patch.object(requests.Session, "post", return_value=_response(200, body)) as post:
        session = api.login("u", "p")
    assert post.call_args.kwargs["json"] == {"username": "u", "password": "p"}
    assert session.headers["Authorization"] == "JWT abc"
    assert session.refresh_token == "def"
    assert session.user == {"id": 1}


def test_login_failure_does_not_leak_credentials():
    with patch.object(requests.Session, "post", return_value=_response(400)):
        with pytest.raises(RuntimeError) as exc:
            api.login("someuser", "hunter2")
    assert "hunter2" not in str(exc.value) and "someuser" not in str(exc.value)


def test_login_without_token_raises():
    with patch.object(requests.Session, "post", return_value=_response(200, {})):
        with pytest.raises(RuntimeError):
            api.login("u", "p")


def test_login_from_env(monkeypatch):
    monkeypatch.setenv("ARCHIDEKT_USERNAME", "u")
    monkeypatch.setenv("ARCHIDEKT_PASSWORD", "p")
    with patch.object(api, "login", return_value="session") as login:
        assert api.loginFromEnv() == "session"
    login.assert_called_once_with("u", "p")


def test_login_from_env_missing(monkeypatch):
    monkeypatch.delenv("ARCHIDEKT_USERNAME", raising=False)
    monkeypatch.delenv("ARCHIDEKT_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        api.loginFromEnv()


def test_get_deck_uses_session():
    session = MagicMock()
    session.get.return_value = _response(404)
    with pytest.raises(RuntimeError):
        api.getDeckById(1, session=session)
    session.get.assert_called_once()
