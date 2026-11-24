import asyncio
import io
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import load_config
from database import Database
from handlers import HELP, register
from telegram_ops import TelegramOps
from worker import Worker

log = logging.getLogger("joiner")


async def main():
    cfg = load_config()
    db = Database(cfg.db_path)

    # flood_sleep_threshold=0: FloodWait Telethon khud sleep na kare, hum handle karenge (stats me dikhega)
    user = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash,
                          flood_sleep_threshold=0, connection_retries=-1)
    bot = TelegramClient(StringSession(), cfg.api_id, cfg.api_hash, connection_retries=-1)

    await user.connect()
    if not await user.is_user_authorized():
        raise SystemExit("SESSION_STRING invalid/expired — tools/gen_session.py dobara chalao.")
    await bot.start(bot_token=cfg.bot_token)

    async def notify(text):
        try:
            await bot.send_message(cfg.owner_id, text, parse_mode=None, link_preview=False)
        except Exception as e:
            log.warning("notify fail (bot ko /start kiya?): %s", type(e).__name__)

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
