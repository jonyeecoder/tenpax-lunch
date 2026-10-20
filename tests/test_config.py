import pytest
from conftest import TEAM_CODE, post
from werkzeug.middleware.proxy_fix import ProxyFix

import app as lunch


@pytest.fixture
def base_config(tmp_path):
    return {"SECRET_KEY": "test-secret", "DATABASE": str(tmp_path / "t.db")}


@pytest.mark.parametrize("secret", ["", "dev-only-not-secret", "change-me-to-a-long-random-string"])
def test_refuses_to_start_without_a_real_secret_key(base_config, secret):
    # Issue #8: a missing key used to fall back to a value published in the repo.
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        lunch.create_app({**base_config, "SECRET_KEY": secret})


def test_refuses_to_start_with_a_misspelt_timezone(base_config):
    with pytest.raises(Exception, match="Asia/Singapour"):
        lunch.create_app({**base_config, "TIMEZONE": "Asia/Singapour"})


def test_session_cookie_is_secure_by_default(base_config, monkeypatch):
    # Issue #11
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    flask_app = lunch.create_app({**base_config, "TEAM_CODE": TEAM_CODE})
    assert flask_app.config["SESSION_COOKIE_SECURE"] is True
    resp = flask_app.test_client().get("/login")
    assert "Secure" in resp.headers["Set-Cookie"]


def test_cookie_secure_can_be_turned_off_for_plain_http(base_config, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "0")
    assert lunch.create_app(base_config).config["SESSION_COOKIE_SECURE"] is False


def test_trust_proxy_uses_forwarded_ip(base_config, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert isinstance(lunch.create_app(base_config).wsgi_app, ProxyFix)


def test_module_builds_app_lazily_for_wsgi(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "from-env")
    monkeypatch.setenv("DATABASE", str(tmp_path / "lazy.db"))
    monkeypatch.delitem(vars(lunch), "app", raising=False)
    from app import app as application  # noqa: PLC0415 (the import is what is under test)

    assert application.config["SECRET_KEY"] == "from-env"
    assert lunch.app is application  # built once, then cached
    monkeypatch.delitem(vars(lunch), "app")
    with pytest.raises(AttributeError):
        lunch.not_a_thing  # noqa: B018


def test_init_db_command(flask_app):
    result = flask_app.test_cli_runner().invoke(args=["init-db"])
    assert "Database ready." in result.output


def test_large_requests_are_rejected(client):
    # Issue #13
    resp = post(client, "/login", username="x" * 20_000, password="x")
    assert resp.status_code == 413


def test_team_clock_uses_the_configured_timezone(base_config):
    flask_app = lunch.create_app({**base_config, "TIMEZONE": "America/New_York"})
    with flask_app.app_context():
        assert str(lunch.team_now().tzinfo) == "America/New_York"
