"""Grant database with change tracking: state/affix.db (SQLite, stdlib only).

grants         one row per grant: current values + first_seen / last_seen / last_changed
grant_changes  every change to a tracked field, with old and new values (append-only)
scrape_runs    one row per scrape of a source, with counts or the error

Identity is the grant's own page URL on the funder's site (grant_id = source:slug).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import audit, config
from .sources.base import Listing

TRACKED = ("title", "description", "amount_text", "amount_min", "amount_max",
           "status", "open_date", "close_date", "url")

SCHEMA = """
CREATE TABLE IF NOT EXISTS grants (
    grant_id     TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT,
    amount_text  TEXT,
    amount_min   INTEGER,
    amount_max   INTEGER,
    status       TEXT,
    open_date    TEXT,
    close_date   TEXT,
    listed       INTEGER NOT NULL DEFAULT 1,   -- 0 once it disappears from the source
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    last_changed TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grant_changes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    grant_id   TEXT NOT NULL REFERENCES grants(grant_id),
    run_id     INTEGER,
    field      TEXT NOT NULL,      -- a tracked field, or 'created' / 'listed'
    old_value  TEXT,
    new_value  TEXT,
    changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scrape_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    found       INTEGER DEFAULT 0,
    new         INTEGER DEFAULT 0,
    changed     INTEGER DEFAULT 0,
    delisted    INTEGER DEFAULT 0,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_changes_grant ON grant_changes(grant_id);
CREATE INDEX IF NOT EXISTS idx_grants_source ON grants(source_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    return config.state_dir() / "affix.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def start_run(conn: sqlite3.Connection, source_id: str) -> int:
    cur = conn.execute("INSERT INTO scrape_runs (source_id, started_at) VALUES (?, ?)", (source_id, _now()))
    conn.commit()
    return cur.lastrowid


def fail_run(conn: sqlite3.Connection, run_id: int, error: str) -> None:
    conn.execute("UPDATE scrape_runs SET finished_at=?, ok=0, error=? WHERE run_id=?", (_now(), error, run_id))
    conn.commit()


def _change(conn, grant_id, run_id, field, old, new, ts):
    conn.execute("INSERT INTO grant_changes (grant_id, run_id, field, old_value, new_value, changed_at) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (grant_id, run_id, field, None if old is None else str(old),
                  None if new is None else str(new), ts))


def record_scrape(conn: sqlite3.Connection, source_id: str, listings: list[Listing],
                  run_id: int | None = None) -> dict:
    """Apply one successful scrape of a source. Returns counts.
    Grants missing from this scrape are marked listed=0 (never deleted)."""
    run_id = run_id or start_run(conn, source_id)
    ts = _now()
    counts = {"found": len(listings), "new": 0, "changed": 0, "delisted": 0, "relisted": 0}
    seen = set()
    with conn:
        for l in listings:
            gid = l.grant_id
            seen.add(gid)
            row = conn.execute("SELECT * FROM grants WHERE grant_id=?", (gid,)).fetchone()
            values = {f: getattr(l, f) for f in TRACKED}
            if row is None:
                conn.execute(
                    f"INSERT INTO grants (grant_id, source_id, {', '.join(TRACKED)}, listed, first_seen, last_seen, last_changed) "
                    f"VALUES (?, ?, {', '.join('?' * len(TRACKED))}, 1, ?, ?, ?)",
                    (gid, source_id, *values.values(), ts, ts, ts))
                _change(conn, gid, run_id, "created", None, l.title, ts)
                counts["new"] += 1
                continue
            diffs = {f: v for f, v in values.items() if row[f] != v}
            if not row["listed"]:
                _change(conn, gid, run_id, "listed", 0, 1, ts)
                counts["relisted"] += 1
            for f, v in diffs.items():
                _change(conn, gid, run_id, f, row[f], v, ts)
            if diffs:
                counts["changed"] += 1
                sets = ", ".join(f"{f}=?" for f in diffs)
                conn.execute(f"UPDATE grants SET {sets}, last_changed=? WHERE grant_id=?", (*diffs.values(), ts, gid))
            conn.execute("UPDATE grants SET listed=1, last_seen=? WHERE grant_id=?", (ts, gid))
        for row in conn.execute("SELECT grant_id FROM grants WHERE source_id=? AND listed=1", (source_id,)).fetchall():
            if row["grant_id"] not in seen:
                conn.execute("UPDATE grants SET listed=0, last_changed=? WHERE grant_id=?", (ts, row["grant_id"]))
                _change(conn, row["grant_id"], run_id, "listed", 1, 0, ts)
                counts["delisted"] += 1
        conn.execute("UPDATE scrape_runs SET finished_at=?, ok=1, found=?, new=?, changed=?, delisted=? WHERE run_id=?",
                     (ts, counts["found"], counts["new"], counts["changed"], counts["delisted"], run_id))
    audit.log("scrape", source_id=source_id, run_id=run_id, **counts)
    return counts


def lifecycle(row, today: date | None = None, closing_days: int = 30) -> str:
    """Where a grant sits right now, from its dates and the funder's own status word.
    One of: closed, opening_soon, closing_soon, open, unknown."""
    today = today or date.today()
    status = (row["status"] or "").strip().lower()
    open_d = date.fromisoformat(row["open_date"]) if row["open_date"] else None
    close_d = date.fromisoformat(row["close_date"]) if row["close_date"] else None
    if not row["listed"] or (close_d and close_d < today) or status == "closed":
        return "closed"
    if open_d and open_d > today:
        return "opening_soon"
    if close_d and close_d <= today + timedelta(days=closing_days):
        return "closing_soon"
    if status == "open" or (open_d and open_d <= today):
        return "open"
    return "unknown"


def grants(conn: sqlite3.Connection, source_id: str | None = None, include_delisted: bool = False):
    q, args = "SELECT * FROM grants WHERE 1=1", []
    if source_id:
        q += " AND source_id=?"; args.append(source_id)
    if not include_delisted:
        q += " AND listed=1"
    return conn.execute(q + " ORDER BY close_date IS NULL, close_date, title", args).fetchall()


def changes(conn: sqlite3.Connection, since: str | None = None, grant_id: str | None = None):
    q, args = "SELECT c.*, g.title FROM grant_changes c JOIN grants g USING (grant_id) WHERE 1=1", []
    if since:
        q += " AND c.changed_at >= ?"; args.append(since)
    if grant_id:
        q += " AND c.grant_id = ?"; args.append(grant_id)
    return conn.execute(q + " ORDER BY c.changed_at, c.id", args).fetchall()
