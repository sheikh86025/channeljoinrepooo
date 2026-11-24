import os
from dataclasses import dataclass

BOT_PREFIX = "🤖 "  # bot ke har message ke aage; isse bot apne hi message ko links na samjhe


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


def _float(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


@dataclass
class Config:
    api_id: int = 0
    api_hash: str = ""
    session_string: str = ""
    bot_token: str = ""
    owner_id: int = 0
    db_path: str = "data/joiner.db"
    delay_min: float = 3.0
    delay_max: float = 6.0
    progress_every: int = 25
    notify_each_fail: bool = True
    max_attempts: int = 3
    flood_notify_min: int = 60
    idle_wait: float = 30.0   # worker idle me kitni der me ek baar jaagta hai
    max_delay_factor: float = 6.0

    @property
    def data_dir(self):
        return os.path.dirname(self.db_path) or "."

    @classmethod
    def from_env(cls):
        return cls(
            api_id=_int("API_ID", 0),
            api_hash=os.getenv("API_HASH", "").strip(),
            bot_token=os.getenv("BOT_TOKEN", "").strip(),
            owner_id=_int("OWNER_ID", 0),
            session_string="".join(os.getenv("SESSION_STRING", "").split()).strip("\"'"),
            db_path=os.getenv("DB_PATH", "data/joiner.db").strip(),
            delay_min=_float("JOIN_DELAY_MIN", 3),
            delay_max=_float("JOIN_DELAY_MAX", 6),
            progress_every=_int("PROGRESS_EVERY", 25),
            notify_each_fail=os.getenv("NOTIFY_EACH_FAIL", "1").strip() != "0",
            max_attempts=_int("MAX_ATTEMPTS", 3),
            flood_notify_min=_int("FLOOD_NOTIFY_MIN", 60),
        )

    def validate(self):
        missing = [n for n, v in (("API_ID", self.api_id), ("API_HASH", self.api_hash),
                                  ("BOT_TOKEN", self.bot_token)) if not v]
        if missing:
            raise SystemExit("Missing env vars: " + ", ".join(missing))
        if self.delay_max < self.delay_min:
            self.delay_max = self.delay_min
