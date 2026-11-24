import asyncio
import io
import logging
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import load_config
from database import Database
from handlers import HELP, register
from login import login_with_phone
from telegram_ops import TelegramOps
from worker import Worker

log = logging.getLogger("joiner")


async def main():
    cfg = load_config()
    db = Database(cfg.db_path)

    bot = TelegramClient(StringSession(), cfg.api_id, cfg.api_hash, connection_retries=-1)
    await bot.start(bot_token=cfg.bot_token)

    async def notify(text):
        try:
            await bot.send_message(cfg.owner_id, text, parse_mode=None, link_preview=False)
        except Exception as e:
            log.warning("notify fail (bot ko /start kiya?): %s", type(e).__name__)

    def new_user(session):
        # flood_sleep_threshold=0: FloodWait Telethon khud sleep na kare, hum handle karenge (stats me dikhega)
        return TelegramClient(StringSession(session), cfg.api_id, cfg.api_hash,
                              flood_sleep_threshold=0, connection_retries=-1)

    # pehle SESSION_STRING, phir login ke baad bani session file, phir PHONE_NUMBER se naya login
    candidates = [cfg.session_string]
    if os.path.exists(cfg.session_file):
        candidates.append(open(cfg.session_file).read().strip())
    user = None
    for s in candidates:
        if not s or s[:1] != "1":
            continue
        try:
            c = new_user(s)
            await c.connect()
            if await c.is_user_authorized():
                user = c
                break
            await c.disconnect()
        except Exception as e:
            log.warning("session try fail: %s", type(e).__name__)
    if user is None:
        if not cfg.phone:
            raise SystemExit("SESSION_STRING invalid/expired — PHONE_NUMBER variable daalo (bot login karwa dega).")
        user = new_user("")
        await user.connect()
        await login_with_phone(bot, user, cfg, notify)

    async def send_report(text, files):
        try:
            await bot.send_message(cfg.owner_id, text, parse_mode=None, link_preview=False)
            for name, data in files:
                buf = io.BytesIO(data)
                buf.name = name
                await bot.send_file(cfg.owner_id, buf, caption=name, force_document=True)
            return True
        except Exception as e:
            log.warning("report send fail: %s", type(e).__name__)
            return False

    worker = Worker(cfg, db, TelegramOps(user), notify, send_report)
    register(bot, cfg, db, worker)

    await notify(f"🟢 Bot chalu. Pending links: {db.pending_count()}\n\n{HELP}")
    await asyncio.gather(worker.run(), bot.run_until_disconnected())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
