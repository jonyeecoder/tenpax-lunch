"""Tenpax Lunch: one shared lunch order for a team of up to 10 coworkers."""

import os
import secrets
import sqlite3
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from dotenv import load_dotenv
from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.cli import with_appcontext
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent

# Values that must never be used as SECRET_KEY: empty, or copied from .env.example / old code.
PLACEHOLDER_SECRETS = frozenset({"", "change-me-to-a-long-random-string", "dev-only-not-secret"})

MAX_TEXT_LENGTH = 100
MAX_USERNAME_LENGTH = 30
MAX_PRICE = Decimal("1000.00")

LOGIN_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_USERNAME = 5
MAX_FAILURES_PER_IP = 20

# Checked when a username doesn't exist, so a wrong username takes as long as a wrong password.
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(16))

bp = Blueprint("lunch", __name__)


# --- App factory ------------------------------------------------------------


def create_app(test_config=None):
    load_dotenv(BASE_DIR / ".env")
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", ""),
        TEAM_CODE=os.environ.get("TEAM_CODE", ""),
        DATABASE=os.environ.get("DATABASE", str(BASE_DIR / "lunch.db")),
        TIMEZONE=os.environ.get("TIMEZONE", "Asia/Singapore"),
        TRUST_PROXY=os.environ.get("TRUST_PROXY") == "1",
        MAX_USERS=10,
        MIN_PASSWORD_LENGTH=8,
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") != "0",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    if app.config["SECRET_KEY"] in PLACEHOLDER_SECRETS:
        raise RuntimeError(
            "SECRET_KEY is missing or still a placeholder. Set a long random value in .env "
            "(see .env.example)."
        )
    ZoneInfo(app.config["TIMEZONE"])  # fail at startup on a misspelt timezone
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

    app.teardown_appcontext(close_db)
    app.register_blueprint(bp)
    app.add_template_filter(money)
    app.add_template_filter(cents_to_dollars, "dollars")
    app.cli.add_command(init_db_command)
    with app.app_context():
        init_db()
    return app


def __getattr__(name):
    # Lets `from app import app` (the WSGI file) and `flask run` build the app on first use,
    # without importing this module creating an app as a side effect.
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)


# --- Database ---------------------------------------------------------------


def db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    db().executescript((BASE_DIR / "schema.sql").read_text())


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create any missing tables."""
    init_db()
    click.echo("Database ready.")


def query(sql, args=(), one=False):
    cur = db().execute(sql, args)
    return cur.fetchone() if one else cur.fetchall()


def execute(sql, args=()):
    cur = db().execute(sql, args)
    db().commit()
    return cur


def get_or_404(sql, args):
    row = query(sql, args, one=True)
    if row is None:
        abort(404)
    return row


# --- Small helpers ----------------------------------------------------------


def team_now():
    return datetime.now(ZoneInfo(current_app.config["TIMEZONE"]))


def today():
    return team_now().date()


def parse_cutoff(text):
    """'HH:MM' -> time, or None if blank or invalid."""
    try:
        return time.fromisoformat(text.strip()) if text and text.strip() else None
    except ValueError:
        return None


def parse_price_cents(text):
    """'6.50' -> 650. None for anything that isn't a price between 0 and MAX_PRICE."""
    try:
        amount = Decimal(text.strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or not Decimal(0) <= amount <= MAX_PRICE:
        return None
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def money(cents):
    return f"${cents / 100:.2f}"


def cents_to_dollars(cents):
    return f"{cents / 100:.2f}"


def form_text(field, max_length):
    """A stripped form value, or None if it's longer than max_length."""
    value = request.form.get(field, "").strip()
    return value if len(value) <= max_length else None


def closed_reason(run):
    """Why a run no longer takes orders, or None while it's open."""
    if run["closed"]:
        return "closed"
    if run["day"] != today().isoformat():
        return "ended"
    cutoff = parse_cutoff(run["cutoff"])
    if cutoff and team_now().time() > cutoff:
        return "past cutoff"
    return None


def to_run(run_id):
    return redirect(url_for("lunch.show_run", run_id=run_id))


# --- Auth -------------------------------------------------------------------


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("lunch.login"))
        return view(*args, **kwargs)

    return wrapped


def log_in(user_id):
    session.clear()
    session["user_id"] = user_id


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def require_organizer(run):
    if run["organizer_id"] != g.user["id"]:
        abort(403)


def too_many_failures(username=None):
    since = (datetime.now(UTC) - LOGIN_WINDOW).isoformat()
    by_ip = query(
        "SELECT COUNT(*) FROM failed_logins WHERE ip = ? AND at > ?",
        (request.remote_addr, since),
        one=True,
    )[0]
    by_user = 0
    if username:
        by_user = query(
            "SELECT COUNT(*) FROM failed_logins WHERE username = ? AND at > ?",
            (username, since),
            one=True,
        )[0]
    return by_ip >= MAX_FAILURES_PER_IP or by_user >= MAX_FAILURES_PER_USERNAME


def record_failure(username=None):
    now = datetime.now(UTC)
    db().execute("DELETE FROM failed_logins WHERE at < ?", ((now - LOGIN_WINDOW).isoformat(),))
    execute(
        "INSERT INTO failed_logins (ip, username, at) VALUES (?, ?, ?)",
        (request.remote_addr, username, now.isoformat()),
    )


@bp.before_app_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf_token", "")):
            abort(400, "Your form expired. Go back, reload the page and try again.")


@bp.before_app_request
def load_user():
    g.user = None
    if "user_id" in session:
        g.user = query(
            "SELECT id, username FROM users WHERE id = ?", (session["user_id"],), one=True
        )
        if g.user is None:
            session.clear()


@bp.app_context_processor
def template_globals():
    return {
        "csrf_token": csrf_token,
        "max_text_length": MAX_TEXT_LENGTH,
        "max_username_length": MAX_USERNAME_LENGTH,
        "min_password_length": current_app.config["MIN_PASSWORD_LENGTH"],
    }


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        config = current_app.config
        username = form_text("username", MAX_USERNAME_LENGTH)
        password = request.form.get("password", "")
        if not config["TEAM_CODE"]:
            flash("Sign-up is closed (no TEAM_CODE set on the server).")
        elif too_many_failures():
            flash("Too many attempts. Try again in 15 minutes.")
        elif not secrets.compare_digest(request.form.get("team_code", ""), config["TEAM_CODE"]):
            record_failure()
            flash("Wrong team code.")
        elif not username:
            flash(f"Pick a username of up to {MAX_USERNAME_LENGTH} characters.")
        elif len(password) < config["MIN_PASSWORD_LENGTH"]:
            flash(f"Pick a password of at least {config['MIN_PASSWORD_LENGTH']} characters.")
        else:
            try:
                # The count check and insert are one statement, so two sign-ups at once
                # can't both slip in as the last member.
                cur = execute(
                    "INSERT INTO users (username, password_hash)"
                    " SELECT ?, ? WHERE (SELECT COUNT(*) FROM users) < ?",
                    (username, generate_password_hash(password), config["MAX_USERS"]),
                )
            except sqlite3.IntegrityError:
                flash("That username is taken.")
            else:
                if cur.rowcount == 0:
                    flash(f"The team is full ({config['MAX_USERS']} people).")
                else:
                    log_in(cur.lastrowid)
                    return redirect(url_for("lunch.index"))
    return render_template("signup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()[:MAX_USERNAME_LENGTH]
        password = request.form.get("password", "")
        if too_many_failures(username):
            flash("Too many attempts. Try again in 15 minutes.")
            return render_template("login.html")
        user = query("SELECT * FROM users WHERE username = ?", (username,), one=True)
        password_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
        if check_password_hash(password_hash, password) and user:
            execute("DELETE FROM failed_logins WHERE username = ?", (username,))
            log_in(user["id"])
            return redirect(url_for("lunch.index"))
        record_failure(username)
        flash("Wrong username or password.")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("lunch.login"))


# --- Lunch runs -------------------------------------------------------------


def get_run(run_id):
    return get_or_404(
        "SELECT runs.*, users.username AS organizer FROM runs"
        " JOIN users ON users.id = runs.organizer_id WHERE runs.id = ?",
        (run_id,),
    )


def get_order(order_id):
    return get_or_404("SELECT * FROM orders WHERE id = ?", (order_id,))


@bp.route("/")
@login_required
def index():
    runs = query(
        "SELECT runs.*, users.username AS organizer, COUNT(orders.id) AS order_count"
        " FROM runs JOIN users ON users.id = runs.organizer_id"
        " LEFT JOIN orders ON orders.run_id = runs.id"
        " WHERE runs.day = ? GROUP BY runs.id ORDER BY runs.id",
        (today().isoformat(),),
    )
    runs = [{**run, "closed_reason": closed_reason(run)} for run in map(dict, runs)]
    return render_template("index.html", runs=runs, today=today())


@bp.post("/runs")
@login_required
def create_run():
    place = form_text("place", MAX_TEXT_LENGTH)
    cutoff_text = request.form.get("cutoff", "").strip()
    cutoff = parse_cutoff(cutoff_text)
    if not place:
        flash(f"Where are we ordering from? (up to {MAX_TEXT_LENGTH} characters)")
    elif cutoff_text and cutoff is None:
        flash("Enter the order-by time as HH:MM, e.g. 11:30.")
    else:
        cur = execute(
            "INSERT INTO runs (day, place, cutoff, organizer_id) VALUES (?, ?, ?, ?)",
            (
                today().isoformat(),
                place,
                cutoff.strftime("%H:%M") if cutoff else None,
                g.user["id"],
            ),
        )
        return to_run(cur.lastrowid)
    return redirect(url_for("lunch.index"))


@bp.route("/runs/<int:run_id>")
@login_required
def show_run(run_id):
    run = get_run(run_id)
    orders = query(
        "SELECT orders.*, users.username FROM orders JOIN users ON users.id = orders.user_id"
        " WHERE run_id = ? ORDER BY users.username",
        (run_id,),
    )
    mine = next((o for o in orders if o["user_id"] == g.user["id"]), None)
    return render_template(
        "run.html",
        run=run,
        orders=orders,
        mine=mine,
        total=sum(o["price_cents"] for o in orders),
        unpaid=sum(o["price_cents"] for o in orders if not o["paid"]),
        closed_reason=closed_reason(run),
        is_organizer=run["organizer_id"] == g.user["id"],
    )


@bp.post("/runs/<int:run_id>/order")
@login_required
def place_order(run_id):
    run = get_run(run_id)
    if closed_reason(run):
        flash("This run isn't taking orders any more.")
        return to_run(run_id)
    item = form_text("item", MAX_TEXT_LENGTH)
    price_cents = parse_price_cents(request.form.get("price", ""))
    if not item or price_cents is None:
        flash(
            f"Enter what you want (up to {MAX_TEXT_LENGTH} characters) and its price, "
            f"between 0 and {MAX_PRICE}."
        )
    else:
        # A changed price needs paying again, so it resets "paid".
        execute(
            "INSERT INTO orders (run_id, user_id, item, price_cents) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (run_id, user_id) DO UPDATE SET item = excluded.item,"
            " paid = CASE WHEN price_cents = excluded.price_cents THEN paid ELSE 0 END,"
            " price_cents = excluded.price_cents",
            (run_id, g.user["id"], item, price_cents),
        )
    return to_run(run_id)


@bp.post("/runs/<int:run_id>/order/delete")
@login_required
def delete_order(run_id):
    if closed_reason(get_run(run_id)):
        flash("This run isn't taking changes any more.")
    else:
        execute("DELETE FROM orders WHERE run_id = ? AND user_id = ?", (run_id, g.user["id"]))
    return to_run(run_id)


@bp.post("/runs/<int:run_id>/closed")
@login_required
def set_closed(run_id):
    require_organizer(get_run(run_id))
    closed = request.form.get("closed") == "1"
    execute("UPDATE runs SET closed = ? WHERE id = ?", (closed, run_id))
    return to_run(run_id)


@bp.post("/orders/<int:order_id>/paid")
@login_required
def set_paid(order_id):
    order = get_order(order_id)
    require_organizer(get_run(order["run_id"]))
    paid = request.form.get("paid") == "1"
    execute("UPDATE orders SET paid = ? WHERE id = ?", (paid, order_id))
    return to_run(order["run_id"])
