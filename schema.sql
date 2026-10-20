CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    place TEXT NOT NULL,
    cutoff TEXT,
    organizer_id INTEGER NOT NULL REFERENCES users (id),
    closed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    item TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    paid INTEGER NOT NULL DEFAULT 0,
    UNIQUE (run_id, user_id)
);

CREATE TABLE IF NOT EXISTS failed_logins (
    id INTEGER PRIMARY KEY,
    ip TEXT NOT NULL,
    username TEXT,
    at TEXT NOT NULL -- UTC, ISO 8601
);

CREATE INDEX IF NOT EXISTS failed_logins_at ON failed_logins (at);
