import asyncio
import glob
import logging
import os
import sys

from telethon import TelegramClient

from app import App, register
from config import Config
from db import DB
from joiner import FLOOD, _errs

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("main")
BAD_TOKEN = _errs("AccessTokenInvalidError", "AccessTokenExpiredError")


async def start_bot_with_retry(bot, token):
    for i in range(12):
        try:
            await bot.start(bot_token=token)
            return
        except BAD_TOKEN:
            raise SystemExit("BOT_TOKEN galat/revoked hai. BotFather se sahi token lekar Railway me daalo.")
        except FLOOD as e:
            wait = getattr(e, "seconds", 30) + 1
        except Exception as e:
            wait = min(5 * 2 ** i, 120)
            log.warning("bot start failed (%s), retry in %ss", type(e).__name__, wait)
        await asyncio.sleep(wait)
    raise SystemExit("Telegram bot start nahi ho paya (Telegram side issue ho sakta hai). Thodi der baad redeploy karo.")


async def main():
    cfg = Config.from_env()
    cfg.validate()
    db = DB(cfg.db_path)

    # token badla ho to purani bot session hatao (warna purana bot hi chalta rahega)
    tid = cfg.bot_token.split(":")[0]
    base = os.path.join(cfg.data_dir, "bot")
    if db.get("bot_id") != tid:
        for f in glob.glob(base + ".session*"):
            os.remove(f)
        db.set("bot_id", tid)

    bot = TelegramClient(base, cfg.api_id, cfg.api_hash, connection_retries=-1,
                         retry_delay=3, auto_reconnect=True)
    await start_bot_with_retry(bot, cfg.bot_token)
    app = App(cfg, db, bot)
    register(bot, app)
    if app.owner:
        await app.boot()
    else:
        log.info("Owner set nahi hai: bot ko Telegram me /start bhejo.")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
