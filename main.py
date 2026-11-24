import asyncio
import io
import logging
import sys

from telethon import TelegramClient, events
from telethon import errors as E
from telethon.sessions import StringSession

from config import BOT_PREFIX, Config
from db import DB, row_url
from joiner import Joiner
from linkparser import extract_links

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("main")

HELP = (
    "Channel Joiner Userbot\n\n"
    "Is chat (Saved Messages) me links bhejo (text ya .txt file) — sab queue me jayenge "
    "aur ek-ek karke join honge.\n\n"
    "/status — progress\n/pause — roko\n/resume — dobara chalao\n"
    "/failed — failed links list\n/retry — failed links dobara try\n"
    "/delay 3 6 — join delay (sec) badlo\n/clear — finished records saaf (pending safe)"
)


class Notifier:
    def __init__(self, client):
        self.client = client

    async def _send(self, coro_factory):
        for _ in range(2):
            try:
                await coro_factory()
                return
            except E.FloodWaitError as e:
                if e.seconds > 300:
                    return
                await asyncio.sleep(e.seconds + 1)
            except Exception:
                log.exception("notify failed")
                return

    async def text(self, msg):
        await self._send(lambda: self.client.send_message("me", BOT_PREFIX + msg[:3900], link_preview=False))

    async def file(self, name, data, caption):
        def make():
            bio = io.BytesIO(data)
            bio.name = name
            return self.client.send_file("me", bio, caption=BOT_PREFIX + caption)
        await self._send(make)


async def connect_with_retry(client):
    for i in range(10):
        try:
            await client.connect()
            return await client.is_user_authorized()
        except Exception as e:
            wait = min(5 * 2 ** i, 120)
            log.warning("connect failed (%s), retry in %ss", type(e).__name__, wait)
            await asyncio.sleep(wait)
    raise SystemExit("Telegram se connect nahi ho paya")


async def supervise(joiner):
    while True:
        try:
            await joiner.run()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("worker crashed, restarting in 5s")
            await asyncio.sleep(5)


async def main():
    cfg = Config.from_env()
    cfg.validate()
    db = DB(cfg.db_path)
    client = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash,
                            flood_sleep_threshold=0, connection_retries=-1,
                            retry_delay=3, auto_reconnect=True)
    if not await connect_with_retry(client):
        raise SystemExit("SESSION_STRING invalid/expired hai. gen_session.py se naya banao.")

    notifier = Notifier(client)
    joiner = Joiner(client, db, cfg, notifier)

    async def command(text):
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        if cmd in ("/start", "/help"):
            await notifier.text(HELP)
        elif cmd == "/status":
            await notifier.text(joiner.status_text())
        elif cmd == "/pause":
            joiner.pause()
            await notifier.text("⏸ Pause kar diya. /resume se continue.")
        elif cmd == "/resume":
            if joiner.fatal:
                await notifier.text("Session problem hai, pehle naya SESSION_STRING lagao.")
            else:
                joiner.resume()
                await notifier.text(f"▶️ Resume. Pending: {db.pending_count()}")
        elif cmd == "/failed":
            rows = db.failed_rows()
            if not rows:
                await notifier.text("Koi failed link nahi 🎉")
            else:
                body = "\n".join(f"{row_url(r)} — {r['detail']}" for r in rows)
                if len(rows) <= 25:
                    await notifier.text(f"❌ Failed ({len(rows)}):\n{body}")
                else:
                    await notifier.file("failed_links.txt", body.encode(), f"Failed ({len(rows)})")
        elif cmd == "/retry":
            n = db.requeue_failed()
            joiner.wake_up()
            await notifier.text(f"🔁 {n} failed links dobara queue me daale")
        elif cmd == "/clear":
            n = db.clear_finished()
            await notifier.text(f"🧹 {n} finished records hata diye. Pending safe hain.")
        elif cmd == "/delay":
            try:
                lo = float(parts[1])
                hi = float(parts[2]) if len(parts) > 2 else lo
                if lo < 0 or hi < lo:
                    raise ValueError
                cfg.delay_min, cfg.delay_max = lo, hi
                await notifier.text(f"Delay ab {lo:g}-{hi:g}s")
            except (IndexError, ValueError):
                await notifier.text("Use: /delay 3 6")
        else:
            await notifier.text("Command samajh nahi aaya. /help dekho.")

    @client.on(events.NewMessage(chats="me"))
    async def on_message(event):
        try:
            msg = event.message
            text = (msg.message or "").strip()
            if text.startswith(BOT_PREFIX.strip()):
                return
            if text.startswith("/"):
                await command(text)
                return
            f = msg.file
            if f is not None:
                name = (getattr(f, "name", "") or "").lower()
                mime = getattr(f, "mime_type", "") or ""
                size = getattr(f, "size", 0) or 0
                if (name.endswith((".txt", ".csv")) or mime.startswith("text/")) and size <= 5_000_000:
                    data = await msg.download_media(file=bytes)
                    text += "\n" + data.decode("utf-8", "ignore")
            items = extract_links(text)
            if not items:
                return
            new, req, dup = db.add_links(items)
            await notifier.text(f"📥 {new} naye links queue me | {req} failed wale dobara | {dup} duplicate skip\n"
                                f"Pending: {db.pending_count()}")
            joiner.wake_up()
        except Exception:
            log.exception("handler error")

    pending = db.pending_count()
    await notifier.text(f"✅ Userbot online. /help dekho." + (f"\nPending {pending} links se resume kar raha hoon." if pending else ""))
    worker = asyncio.create_task(supervise(joiner))
    try:
        await client.run_until_disconnected()
    finally:
        joiner.stop()
        worker.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
