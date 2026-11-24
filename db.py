import os
import sqlite3
import time

from linkparser import to_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | joined | already | request_sent | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    detail TEXT DEFAULT '',
    title TEXT DEFAULT '',
    added REAL, updated REAL,
    UNIQUE(kind, key)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_status ON links(status, id);
"""


class DB:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.c = sqlite3.connect(path)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)
        self.c.commit()

    def add_links(self, items):
        """Returns (new, requeued, duplicates)."""
        new = req = dup = 0
        now = time.time()
        for kind, key in items:
            r = self.c.execute("SELECT id,status FROM links WHERE kind=? AND key=?", (kind, key)).fetchone()
            if r is None:
                self.c.execute("INSERT INTO links(kind,key,added,updated) VALUES(?,?,?,?)", (kind, key, now, now))
                new += 1
            elif r["status"] == "failed":
                self.c.execute("UPDATE links SET status='pending',attempts=0,detail='',updated=? WHERE id=?", (now, r["id"]))
                req += 1
            else:
                dup += 1
        self.c.commit()
        return new, req, dup

    def next_pending(self):
        return self.c.execute("SELECT * FROM links WHERE status='pending' ORDER BY id LIMIT 1").fetchone()

    def mark(self, rid, status, detail="", title=""):
        self.c.execute("UPDATE links SET status=?,detail=?,title=?,updated=? WHERE id=?",
                       (status, detail, title, time.time(), rid))
        self.c.commit()

    def bump_attempt(self, rid, detail=""):
        self.c.execute("UPDATE links SET attempts=attempts+1,detail=?,updated=? WHERE id=?", (detail, time.time(), rid))
        self.c.commit()
        return self.c.execute("SELECT attempts FROM links WHERE id=?", (rid,)).fetchone()["attempts"]

    def counts(self):
        d = {"pending": 0, "joined": 0, "already": 0, "request_sent": 0, "failed": 0}
        for r in self.c.execute("SELECT status, COUNT(*) n FROM links GROUP BY status"):
            d[r["status"]] = r["n"]
        return d

    def pending_count(self):
        return self.counts()["pending"]

    def failed_rows(self):
        return self.c.execute("SELECT * FROM links WHERE status='failed' ORDER BY id").fetchall()

    def requeue_failed(self):
        n = self.c.execute("UPDATE links SET status='pending',attempts=0,detail='',updated=? WHERE status='failed'",
                           (time.time(),)).rowcount
        self.c.commit()
        return n

    def get(self, key, default=None):
        r = self.c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set(self, key, value):
        self.c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.c.commit()

    def delete(self, key):
        self.c.execute("DELETE FROM settings WHERE key=?", (key,))
        self.c.commit()

    def rows_by_status(self, status):
        return self.c.execute("SELECT * FROM links WHERE status=? ORDER BY id", (status,)).fetchall()

    def count_since(self, status, ts):
        return self.c.execute("SELECT COUNT(*) n FROM links WHERE status=? AND updated>=?", (status, ts)).fetchone()["n"]

    def clear_finished(self):
        n = self.c.execute("DELETE FROM links WHERE status!='pending'").rowcount
        self.c.commit()
        return n


def row_url(row):
    return to_url(row["kind"], row["key"])
