"""Configuration loaded from environment variables / .env file."""
import os
from dataclasses import dataclass

try:  # optional dependency
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


@dataclass
class Config:
    api_id: int
    api_hash: str
    session: str = "joiner_session"
    session_string: str = ""
    phone: str = ""
    owner_id: int = 0
    db_path: str = "data/joiner.db"
    reports_dir: str = "data/reports"
    # Base delay (seconds) between two join attempts. Adaptive: it grows
    # automatically after a FloodWait and shrinks back towards this value.
    join_delay: float = 1.0
    max_delay: float = 30.0
    # Seconds of silence (no new links, nothing pending) before the final
    # report is sent. Lets you send links in several messages.
    finish_debounce: float = 10.0
    # FloodWait >= this many seconds triggers a notification message.
    flood_notify_min: int = 120


def load_config() -> Config:
    api_id = _int("API_ID")
    api_hash = os.getenv("API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit("API_ID and API_HASH are required (see .env.example).")
    return Config(
        api_id=api_id,
        api_hash=api_hash,
        session=os.getenv("SESSION_NAME", "joiner_session").strip() or "joiner_session",
        session_string=os.getenv("SESSION_STRING", "").strip(),
        phone=os.getenv("PHONE", "").strip(),
        owner_id=_int("OWNER_ID"),
        db_path=os.getenv("DB_PATH", "data/joiner.db").strip() or "data/joiner.db",
        reports_dir=os.getenv("REPORTS_DIR", "data/reports").strip() or "data/reports",
        join_delay=_float("JOIN_DELAY", 1.0),
        max_delay=_float("MAX_DELAY", 30.0),
        finish_debounce=_float("FINISH_DEBOUNCE", 10.0),
        flood_notify_min=_int("FLOOD_NOTIFY_MIN", 120),
    )
