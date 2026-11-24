import os
from dataclasses import dataclass

try:  # local run ke liye .env support (optional)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    owner_id: int
    session_string: str
    db_path: str = "joiner.db"
    start_delay: float = 2.0      # shuruaati gap (sec) har join ke beech
    min_delay: float = 1.0        # isse kam kabhi nahi hoga
    max_delay: float = 30.0       # FloodWait ke baad gap badhta hai, isse zyada nahi
    min_free: int = 20            # channel limit full hone par itne leave hone par auto resume
    report_debounce: float = 20.0  # queue khali hone ke itne sec baad final report


def _need(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Environment variable missing: {name}")
    return value


def load_config():
    return Config(
        api_id=int(_need("API_ID")),
        api_hash=_need("API_HASH"),
        bot_token=_need("BOT_TOKEN"),
        owner_id=int(_need("OWNER_ID")),
        session_string=_need("SESSION_STRING"),
        db_path=os.environ.get("DB_PATH", "joiner.db"),
        start_delay=float(os.environ.get("START_DELAY", 2)),
        min_delay=float(os.environ.get("MIN_DELAY", 1)),
        max_delay=float(os.environ.get("MAX_DELAY", 30)),
        min_free=int(os.environ.get("MIN_FREE", 20)),
        report_debounce=float(os.environ.get("REPORT_DEBOUNCE", 20)),
    )
