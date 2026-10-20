import pytest
from conftest import PASSWORD, TEAM_CODE, page, post

import app as lunch


def signup(client, **overrides):
    form = {"team_code": TEAM_CODE, "username": "dom", "password": PASSWORD, **overrides}
    return post(client, "/signup", **form)


def test_logged_out_visitors_are_sent_to_login(client):
    assert client.get("/").headers["Location"] == "/login"


def test_login_and_signup_pages_render(client):
    assert "Log in · Tenpax Lunch" in page(client, "/login")
    assert "Join · Tenpax Lunch" in page(client, "/signup")


def test_signup_logs_you_in(client):
    resp = signup(client)
    assert resp.headers["Location"] == "/"
    assert "Start a lunch run" in page(client, "/")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"team_code": "wrong"}, "Wrong team code."),
        ({"username": "   "}, "Pick a username"),
        ({"username": "x" * 31}, "Pick a username"),  # issue #13
        ({"password": "short"}, "at least 8 characters"),  # issue #19: one MIN_PASSWORD_LENGTH
    ],
)
def test_signup_validation(client, overrides, message):
    resp = signup(client, **overrides)
    assert resp.status_code == 200
    assert message in resp.get_data(as_text=True)


def test_signup_closed_without_team_code(client, flask_app):
    flask_app.config["TEAM_CODE"] = ""
    assert "Sign-up is closed" in signup(client).get_data(as_text=True)


def test_duplicate_username(client, user):
    user("dom")
    assert "That username is taken." in signup(client).get_data(as_text=True)


def test_team_is_capped(client, flask_app, user):
    for i in range(flask_app.config["MAX_USERS"]):
        user(f"user{i}")
    text = signup(client).get_data(as_text=True)
    assert f"The team is full ({flask_app.config['MAX_USERS']} people)." in text


def test_cap_check_and_insert_are_one_statement(flask_app, user, db):
    # Issue #7: the cap is enforced inside the INSERT itself, so even a sign-up that passed
    # every earlier check can't push the team over the limit.
    flask_app.config["MAX_USERS"] = 1
    user("first")
    with flask_app.test_request_context():
        cur = lunch.execute(
            "INSERT INTO users (username, password_hash)"
            " SELECT ?, ? WHERE (SELECT COUNT(*) FROM users) < ?",
            ("second", "x", 1),
        )
        assert cur.rowcount == 0
    assert len(db("SELECT * FROM users")) == 1


def test_wrong_team_codes_are_rate_limited(client):
    # Issue #9
    for _ in range(lunch.MAX_FAILURES_PER_IP):
        signup(client, team_code="guess")
    assert "Too many attempts" in signup(client).get_data(as_text=True)


def test_login_and_logout(client, user):
    user("dom")
    resp = post(client, "/login", username="dom", password=PASSWORD)
    assert resp.headers["Location"] == "/"
    assert client.get("/").status_code == 200
    assert post(client, "/logout").headers["Location"] == "/login"
    assert client.get("/").status_code == 302


@pytest.mark.parametrize("username", ["dom", "nobody"])
def test_login_failure(client, user, username):
    user("dom")
    resp = post(client, "/login", username=username, password="wrong-password")
    assert "Wrong username or password." in resp.get_data(as_text=True)


def test_unknown_username_still_checks_a_password_hash(client, monkeypatch):
    # Issue #12: both paths do the slow hash check, so timing doesn't reveal real usernames.
    checked = []
    monkeypatch.setattr(lunch, "check_password_hash", lambda h, p: checked.append(h) or False)
    post(client, "/login", username="nobody", password="whatever")
    assert checked == [lunch.DUMMY_PASSWORD_HASH]


def test_repeated_wrong_passwords_lock_the_username(client, user):
    # Issue #9
    user("dom")
    for _ in range(lunch.MAX_FAILURES_PER_USERNAME):
        post(client, "/login", username="dom", password="wrong-password")
    resp = post(client, "/login", username="dom", password=PASSWORD)
    assert "Too many attempts" in resp.get_data(as_text=True)


def test_successful_login_clears_earlier_failures(client, user, db):
    user("dom")
    post(client, "/login", username="dom", password="wrong-password")
    post(client, "/login", username="dom", password=PASSWORD)
    assert db("SELECT * FROM failed_logins WHERE username = 'dom'") == []


def test_old_failures_are_forgotten(client, user, db):
    user("dom")
    db("INSERT INTO failed_logins (ip, username, at) VALUES ('1.2.3.4', 'dom', '2000-01-01')")
    post(client, "/login", username="dom", password="wrong-password")
    assert db("SELECT * FROM failed_logins WHERE at = '2000-01-01'") == []


def test_session_for_deleted_user_is_cleared(user, db):
    dom = user("dom")
    db("DELETE FROM users WHERE username = 'dom'")
    assert dom.get("/").headers["Location"] == "/login"


@pytest.mark.parametrize("token", [None, "", "forged"])
def test_posts_need_a_valid_csrf_token(user, token):
    # Issue #10
    dom = user("dom")
    data = {"place": "Anywhere"}
    if token is not None:
        data["csrf_token"] = token
    resp = dom.post("/runs", data=data)
    assert resp.status_code == 400
