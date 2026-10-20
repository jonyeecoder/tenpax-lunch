import os
import sqlite3
MIN_PASSWORD_LENGTH = 6
from datetime import date
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MAX_USERS = 10

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-not-secret"),
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
)
TEAM_CODE = os.environ.get("TEAM_CODE")
DATABASE = os.environ.get("DATABASE", os.path.join(app.root_path, "lunch.db"))


# --- Database ---------------------------------------------------------------

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    with app.app_context():
        with open(os.path.join(app.root_path, "schema.sql")) as f:
            db().executescript(f.read())


# --- Auth -------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def load_user():
    g.user = None
    if "user_id" in session:
        g.user = db().execute("SELECT id, username FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if g.user is None:
            session.clear()


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        count = db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if not TEAM_CODE:
            flash("Sign-up is closed (no TEAM_CODE set on the server).")
        elif request.form["team_code"] != TEAM_CODE:
            flash("Wrong team code.")
        elif count >= MAX_USERS:
            flash(f"The team is full ({MAX_USERS} people).")
        elif not username or len(password) < MIN_PASSWORD_LENGTH:
            flash("Pick a username and a password of at least {MIN_PASSWORD_LENGTH} characters.")
        else:
            try:
                cur = db().execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db().commit()
            except sqlite3.IntegrityError:
                flash("That username is taken.")
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                return redirect(url_for("index"))
    return render_template("signup.html",min_password_length=MIN_PASSWORD_LENGTH)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db().execute(
            "SELECT * FROM users WHERE username = ?", (request.form["username"].strip(),)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        flash("Wrong username or password.")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --- Lunch runs -------------------------------------------------------------

def get_run(run_id):
    run = db().execute(
        "SELECT runs.*, users.username AS organizer FROM runs"
        " JOIN users ON users.id = runs.organizer_id WHERE runs.id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        abort(404)
    return run


@app.route("/")
@login_required
def index():
    runs = db().execute(
        "SELECT runs.*, users.username AS organizer, COUNT(orders.id) AS order_count"
        " FROM runs JOIN users ON users.id = runs.organizer_id"
        " LEFT JOIN orders ON orders.run_id = runs.id"
        " WHERE runs.day = ? GROUP BY runs.id ORDER BY runs.id",
        (date.today().isoformat(),),
    ).fetchall()
    return render_template("index.html", runs=runs, today=date.today())


@app.post("/runs")
@login_required
def create_run():
    place = request.form["place"].strip()
    if not place:
        flash("Where are we ordering from?")
        return redirect(url_for("index"))
    cur = db().execute(
        "INSERT INTO runs (day, place, cutoff, organizer_id) VALUES (?, ?, ?, ?)",
        (date.today().isoformat(), place, request.form.get("cutoff") or None, g.user["id"]),
    )
    db().commit()
    return redirect(url_for("show_run", run_id=cur.lastrowid))


@app.route("/runs/<int:run_id>")
@login_required
def show_run(run_id):
    run = get_run(run_id)
    orders = db().execute(
        "SELECT orders.*, users.username FROM orders JOIN users ON users.id = orders.user_id"
        " WHERE run_id = ? ORDER BY users.username",
        (run_id,),
    ).fetchall()
    mine = next((o for o in orders if o["user_id"] == g.user["id"]), None)
    total = sum(o["price_cents"] for o in orders)
    unpaid = sum(o["price_cents"] for o in orders if not o["paid"])
    return render_template(
        "run.html", run=run, orders=orders, mine=mine, total=total, unpaid=unpaid,
        is_organizer=run["organizer_id"] == g.user["id"],
    )


@app.post("/runs/<int:run_id>/order")
@login_required
def place_order(run_id):
    run = get_run(run_id)
    if run["closed"]:
        flash("This run is closed.")
        return redirect(url_for("show_run", run_id=run_id))
    item = request.form["item"].strip()
    try:
        price_cents = round(float(request.form["price"]) * 100)
    except ValueError:
        price_cents = -1
    if not item or price_cents < 0:
        flash("Enter what you want and its price, e.g. 6.50.")
    else:
        db().execute(
            "INSERT INTO orders (run_id, user_id, item, price_cents) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (run_id, user_id) DO UPDATE SET item = excluded.item, price_cents = excluded.price_cents",
            (run_id, g.user["id"], item, price_cents),
        )
        db().commit()
    return redirect(url_for("show_run", run_id=run_id))


@app.post("/runs/<int:run_id>/order/delete")
@login_required
def delete_order(run_id):
    if not get_run(run_id)["closed"]:
        db().execute("DELETE FROM orders WHERE run_id = ? AND user_id = ?", (run_id, g.user["id"]))
        db().commit()
    return redirect(url_for("show_run", run_id=run_id))


@app.post("/runs/<int:run_id>/close")
@login_required
def toggle_closed(run_id):
    run = get_run(run_id)
    if run["organizer_id"] != g.user["id"]:
        abort(403)
    db().execute("UPDATE runs SET closed = NOT closed WHERE id = ?", (run_id,))
    db().commit()
    return redirect(url_for("show_run", run_id=run_id))


@app.post("/orders/<int:order_id>/paid")
@login_required
def toggle_paid(order_id):
    order = db().execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)
    if get_run(order["run_id"])["organizer_id"] != g.user["id"]:
        abort(403)
    db().execute("UPDATE orders SET paid = NOT paid WHERE id = ?", (order_id,))
    db().commit()
    return redirect(url_for("show_run", run_id=order["run_id"]))


@app.template_filter("money")
def money(cents):
    return f"${cents / 100:.2f}"


init_db()

if __name__ == "__main__":
    app.run(debug=True)
