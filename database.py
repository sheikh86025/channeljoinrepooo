import os
import sqlite3
from datetime import datetime, timezone

DONE_EXCLUDE = "('pending','processing')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    val TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT DEFAULT '',
    title TEXT DEFAULT '',
    channel_id TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    reported INTEGER DEFAULT 0,
    added_at TEXT,
    done_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_links_status ON links(status, id);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Saari progress SQLite me. Restart par 'processing' wale links wapas pending ho jaate hain."""

    def __init__(self, path):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.execute("UPDATE links SET status='pending' WHERE status='processing'")
        self.conn.commit()

    # ---- queue ----
    def add(self, links):
        """links: [(kind, val, url, key)] -> (new_count, [(url, old_status)])"""
        new, dups = 0, []
        for kind, val, url, key in links:
            row = self.conn.execute("SELECT status FROM links WHERE key=?", (key,)).fetchone()
            if row:
                dups.append((url, row["status"]))
                continue
            self.conn.execute(
                "INSERT INTO links (key, kind, val, url, added_at) VALUES (?,?,?,?,?)",
                (key, kind, val, url, _now()),
            )
            new += 1
        self.conn.commit()
        return new, dups

    def next_pending(self):
        return self.conn.execute(
            "SELECT * FROM links WHERE status='pending' ORDER BY id LIMIT 1").fetchone()

    def start(self, link_id):
        self.conn.execute(
            "UPDATE links SET status='processing', attempts=attempts+1 WHERE id=?", (link_id,))
        self.conn.commit()

    def finish(self, link_id, status, detail="", title="", channel_id=""):
        self.conn.execute(
            "UPDATE links SET status=?, detail=?, title=?, channel_id=?, done_at=? WHERE id=?",
            (status, detail, title, channel_id, _now(), link_id))
        self.conn.commit()

    def requeue(self, link_id):
        self.conn.execute("UPDATE links SET status='pending' WHERE id=?", (link_id,))
        self.conn.commit()

    def retry_failed(self):
        cur = self.conn.execute(
            "UPDATE links SET status='pending', attempts=0, reported=0, detail='' WHERE status='failed'")
        self.conn.commit()
        return cur.rowcount

    # ---- stats / report ----
    def counts(self, batch_only=False):
        q = "SELECT status, COUNT(*) c FROM links"
        if batch_only:
            q += " WHERE reported=0"
        q += " GROUP BY status"
        return {r["status"]: r["c"] for r in self.conn.execute(q)}

    def pending_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM links WHERE status IN ('pending','processing')").fetchone()[0]

    def has_unreported(self):
        return self.conn.execute("SELECT 1 FROM links WHERE reported=0 LIMIT 1").fetchone() is not None

    def processing_row(self):
        return self.conn.execute(
            "SELECT * FROM links WHERE status='processing' ORDER BY id LIMIT 1").fetchone()

    def rows_for_report(self, batch_only=True):
        q = f"SELECT * FROM links WHERE status NOT IN {DONE_EXCLUDE}"
        if batch_only:
            q += " AND reported=0"
        return self.conn.execute(q + " ORDER BY id").fetchall()

    def mark_reported(self):
        self.conn.execute(
            f"UPDATE links SET reported=1 WHERE reported=0 AND status NOT IN {DONE_EXCLUDE}")
        self.conn.commit()

    # ---- meta ----
    def meta_get(self, key, default=""):
        row = self.conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

    def meta_set(self, key, value):
        self.conn.execute(
            "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, str(value)))
        self.conn.commit()
