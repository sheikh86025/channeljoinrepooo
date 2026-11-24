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
    phone: str = ""               # PHONE_NUMBER variable: bot khud login karwayega (OTP bot me bhejna)
    session_file: str = "session.txt"  # login ke baad string yahan bhi save hoti hai
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


def clean_session(raw):
    """Railway me paste karte time aksar quotes / space / 'SESSION_STRING=' saath aa jaata hai — hata do."""
    s = (raw or "").strip().strip("\"'`").strip()
    if "=" in s[:25]:  # 'SESSION_STRING=1BVts...' paste ho gaya
        s = s.split("=", 1)[1].strip().strip("\"'`")
    return "".join(s.split())  # beech ka space / line break


def check_session(session):
    """Telethon string hamesha '1' se shuru hoti hai. Pyrogram wali string yahan nahi chalti."""
    if session[:1] != "1":
        raise SystemExit(
            f"SESSION_STRING Telethon wali nahi hai (shuruaat: '{session[:2]}', lambai: {len(session)}). "
            "Telethon string '1' se shuru hoti hai aur ~353 characters ki hoti hai. "
            "Pyrogram ya kisi aur bot ki string nahi chalegi — gen_session.py se nayi banao.")
    return session


def load_config():
    phone = os.environ.get("PHONE_NUMBER", "").strip().replace(" ", "")
    session = clean_session(os.environ.get("SESSION_STRING", ""))
    if session and session[:1] != "1":
        if not phone:
            check_session(session)  # error de do
        print(f"SESSION_STRING Telethon wali nahi hai (shuruaat: '{session[:2]}') — ignore, PHONE_NUMBER se login hoga.")
        session = ""
    if not session and not phone:
        raise SystemExit("SESSION_STRING ya PHONE_NUMBER me se ek variable zaroor daalo.")
    db_path = os.environ.get("DB_PATH", "joiner.db")
    return Config(
        api_id=int(_need("API_ID")),
        api_hash=_need("API_HASH"),
        bot_token=_need("BOT_TOKEN"),
        owner_id=int(_need("OWNER_ID")),
        session_string=session,
        db_path=db_path,
        phone=phone,
        session_file=os.environ.get("SESSION_FILE", os.path.join(os.path.dirname(db_path) or ".", "session.txt")),
        start_delay=float(os.environ.get("START_DELAY", 2)),
        min_delay=float(os.environ.get("MIN_DELAY", 1)),
        max_delay=float(os.environ.get("MAX_DELAY", 30)),
        min_free=int(os.environ.get("MIN_FREE", 20)),
        report_debounce=float(os.environ.get("REPORT_DEBOUNCE", 20)),
    )
