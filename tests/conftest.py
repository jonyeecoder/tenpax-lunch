from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import app as lunch

TEAM_CODE = "team-code"
PASSWORD = "password1"
SGT = ZoneInfo("Asia/Singapore")


@pytest.fixture
def clock(monkeypatch):
    """The team's current time. Tests move it with `clock.now = ...`."""

    class Clock:
        now = datetime(2026, 10, 20, 10, 0, tzinfo=SGT)

    monkeypatch.setattr(lunch, "team_now", lambda: Clock.now)
    return Clock


@pytest.fixture
def flask_app(tmp_path, clock):
    return lunch.create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "TEAM_CODE": TEAM_CODE,
            "DATABASE": str(tmp_path / "test.db"),
            "TIMEZONE": "Asia/Singapore",
            "SESSION_COOKIE_SECURE": False,
        }
    )


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def db(flask_app):
    """Run SQL against the test database directly."""

    def run(sql, args=()):
        with flask_app.app_context():
            rows = lunch.query(sql, args)
            lunch.db().commit()
            return rows

    return run


def post(client, url, **data):
    """POST a form the way the browser would, including the CSRF token."""
    with client.session_transaction() as sess:
        token = sess.setdefault("csrf_token", "test-csrf-token")
    return client.post(url, data={**data, "csrf_token": token})


@pytest.fixture
def user(flask_app):
    """Factory for a signed-up, logged-in test client: `alice = user("alice")`."""

    def make(name):
        c = flask_app.test_client()
        resp = post(c, "/signup", team_code=TEAM_CODE, username=name, password=PASSWORD)
        assert resp.status_code == 302, "sign-up should succeed"
        return c

    return make


@pytest.fixture
def alice(user):
    return user("alice")


@pytest.fixture
def bob(user):
    return user("bob")


@pytest.fixture
def run_url(alice):
    """Today's run at the chicken rice stall, organised by alice, order by 11:30."""
    resp = post(alice, "/runs", place="Chicken rice stall", cutoff="11:30")
    return resp.headers["Location"]


def page(client, url):
    return client.get(url).get_data(as_text=True)
