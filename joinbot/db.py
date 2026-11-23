"""SQLite persistence: every link and its status survive restarts."""
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

PENDING = "pending"
PROCESSING = "processing"
JOINED = "joined"
ALREADY = "already"
INVALID = "invalid"  # invalid invite hash / username
EXPIRED = "expired"  # private channel / invite expired / revoked
NOT_FOUND = "not_found"
REQUEST_SENT = "request_sent"
ERROR = "error"

ALL_STATUSES = (
    PENDING, PROCESSING, JOINED, ALREADY, INVALID, EXPIRED,
    NOT_FOUND, REQUEST_SENT, ERROR,
)

STATUS_LABELS = {
    JOINED: "Successfully Joined",
    ALREADY: "Already Joined",
    INVALID: "Invalid Invite Link",
    EXPIRED: "Private Channel / Invite Expired",
    NOT_FOUND: "Channel Not Found",
    REQUEST_SENT: "Join Request Sent",
    ERROR: "Other Errors",
}

# Report groupings
INVALID_GROUP = (INVALID, EXPIRED)
FAILED_GROUP = (NOT_FOUND, ERROR)


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    ref TEXT NOT NULL,
                    original TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    detail TEXT DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    added_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_links_status ON links(status, id);
                CREATE TABLE IF NOT EXISTS meta (
                    k TEXT PRIMARY KEY,
                    v TEXT
                );
                """
            )

    # ---- links -------------------------------------------------------
    def add_links(self, links: Iterable) -> Tuple[int, int]:
        """Insert ParsedLink items. Returns (new, duplicates)."""
        new = dup = 0
        now = time.time()
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                for l in links:
                    cur = self.conn.execute(
                        "INSERT OR IGNORE INTO links(key,kind,ref,original,status,added_at,updated_at)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (l.key, l.kind, l.ref, l.original, PENDING, now, now),
                    )
                    if cur.rowcount:
                        new += 1
                    else:
                        dup += 1
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return new, dup

    def next_pending(self) -> Optional[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM links WHERE status=? ORDER BY id LIMIT 1", (PENDING,)
            ).fetchone()

    def set_status(self, link_id: int, status: str, detail: str = "") -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE links SET status=?, detail=?, updated_at=?,"
                " attempts=attempts+(CASE WHEN ?=? THEN 1 ELSE 0 END) WHERE id=?",
                (status, detail[:500], time.time(), status, PROCESSING, link_id),
            )

    def reset_processing(self) -> int:
        """After a crash/restart, anything left 'processing' goes back to pending."""
        with self.lock:
            return self.conn.execute(
                "UPDATE links SET status=?, updated_at=? WHERE status=?",
                (PENDING, time.time(), PROCESSING),
            ).rowcount

    def retry_failed(self) -> int:
        with self.lock:
            return self.conn.execute(
                "UPDATE links SET status=?, detail='', updated_at=? WHERE status IN (?,?)",
                (PENDING, time.time(), ERROR, NOT_FOUND),
            ).rowcount

    def counts(self) -> Dict[str, int]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) c FROM links GROUP BY status"
            ).fetchall()
        out = {s: 0 for s in ALL_STATUSES}
        for r in rows:
            out[r["status"]] = r["c"]
        out["total"] = sum(out[s] for s in ALL_STATUSES)
        return out

    def list_by_status(self, statuses: Sequence[str]) -> List[sqlite3.Row]:
        q = ",".join("?" * len(statuses))
        with self.lock:
            return self.conn.execute(
                f"SELECT * FROM links WHERE status IN ({q}) ORDER BY id", tuple(statuses)
            ).fetchall()

    def all_rows(self) -> List[sqlite3.Row]:
        with self.lock:
            return self.conn.execute("SELECT * FROM links ORDER BY id").fetchall()

    # ---- meta --------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        with self.lock:
            r = self.conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return r["v"] if r and r["v"] is not None else default

    def set_meta(self, key: str, value) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (key, str(value)),
            )
