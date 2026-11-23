"""Telethon user-client: receives links/commands and drives the Joiner."""
import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from . import db as D
from . import reports
from .config import load_config
from .joiner import Joiner
from .parser import extract_links

MARK = "⁣"  # invisible marker: our own messages are never parsed as input
MAX_TXT_BYTES = 5 * 1024 * 1024

HELP = (
    "🤖 Bulk Channel Joiner\n\n"
    "Send your channel links (as text, in one or more messages, or as a .txt file) "
    "to your Saved Messages. Joining starts automatically.\n\n"
    "/stats - live progress\n"
    "/report - resend the report\n"
    "/pause, /resume - pause / resume joining\n"
    "/retry - re-queue Failed links (not found / other errors)\n"
    "/delay <sec> - set base delay between joins (adaptive on FloodWait)\n"
    "/help - this message"
)


def setup_logging() -> None:
    os.makedirs("data", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = RotatingFileHandler("data/joiner.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    logging.getLogger("telethon").setLevel(logging.WARNING)


async def amain() -> None:
    setup_logging()
    log = logging.getLogger("joinbot")
    cfg = load_config()
    database = D.Database(cfg.db_path)

    # SESSION_STRING is preferred on hosted (non-interactive) deployments.
    # Strip accidental wrapping quotes sometimes pasted into hosting dashboards.
    raw_session_string = (cfg.session_string or "").strip()
    if len(raw_session_string) >= 2 and raw_session_string[0] == raw_session_string[-1] and raw_session_string[0] in ('"', "'"):
        raw_session_string = raw_session_string[1:-1].strip()

    if raw_session_string:
        try:
            session = StringSession(raw_session_string)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "SESSION_STRING is not a valid Telethon StringSession. "
                "Generate a fresh StringSession and paste its value without extra quotes."
            ) from exc
    else:
        session = cfg.session

    client = TelegramClient(
        session,
        cfg.api_id,
        cfg.api_hash,
        flood_sleep_threshold=0,  # we handle FloodWait ourselves (visible in /stats)
        connection_retries=None,  # reconnect forever
        retry_delay=2,
        auto_reconnect=True,
    )

    # Connect first and verify authorization. Calling client.start() unconditionally
    # can invoke input() on a server and crash with EOFError.
    await client.connect()
    if not await client.is_user_authorized():
        if raw_session_string:
            raise RuntimeError(
                "SESSION_STRING was parsed but is not authorized for a Telegram account. "
                "Generate a new authenticated Telethon StringSession; do not use an API hash "
                "or bot token in SESSION_STRING."
            )
        if not __import__("sys").stdin.isatty():
            raise RuntimeError(
                "No authorized Telegram session found. Set a valid authenticated "
                "SESSION_STRING, or run once in an interactive terminal to log in "
                "and persist the SESSION_NAME session file."
            )
        phone = (cfg.phone or input("Phone number (with country code): ")).strip()
        await client.start(phone=phone)
    me = await client.get_me()
    log.info("Logged in as %s (id=%s)", me.username or me.first_name, me.id)

    def target_chat() -> int:
        v = database.get_meta("notify_chat")
        return int(v) if v else me.id

    async def say(text: str, chat=None, files=None) -> None:
        chat = chat or target_chat()
        if files:
            for i, f in enumerate(files):
                await client.send_file(chat, f, caption=(MARK + text) if i == 0 else MARK)
        else:
            await client.send_message(chat, MARK + text, parse_mode=None, link_preview=False)

    async def notify(text: str) -> None:
        try:
            await say(text)
        except Exception:
            log.exception("notify failed")

    async def send_final_report() -> None:
        text, files = reports.build_report(database, cfg.reports_dir)
        # message first (can be long), then files
        await client.send_message(target_chat(), MARK + text, parse_mode=None, link_preview=False)
        for f in files:
            await client.send_file(target_chat(), f, caption=MARK + os.path.basename(f))

    joiner = Joiner(client, database, cfg, notify, send_final_report)

    async def add_text(text: str, chat_id: int, extra_urls=()) -> None:
        links = extract_links(text, extra_urls)
        if not links:
            await say("No Telegram links found in that message.", chat_id)
            return
        new, dup = database.add_links(links)
        database.set_meta("notify_chat", chat_id)
        if new:
            database.set_meta("batch_active", "1")
        c = database.counts()
        await say(
            f"📥 Links found: {len(links)} | New: {new} | Duplicates skipped: {dup}\n"
            f"Pending now: {c[D.PENDING]} | Total in DB: {c['total']}\n"
            "Joining automatically. Use /stats for progress.",
            chat_id,
        )
        joiner.kick()

    @client.on(events.NewMessage)
    async def on_message(event):
        try:
            if not event.is_private:
                return
            if not (event.chat_id == me.id or (cfg.owner_id and event.sender_id == cfg.owner_id)):
                return
            text = event.raw_text or ""
            if text.startswith(MARK):
                return
            chat_id = event.chat_id

            if text.startswith("/"):
                await handle_command(text, chat_id)
                return

            extra = []
            for ent in event.message.entities or []:
                url = getattr(ent, "url", None)
                if url:
                    extra.append(url)

            doc = event.message.document
            if doc:
                name = ""
                for a in doc.attributes:
                    name = getattr(a, "file_name", name) or name
                if name.startswith("report_"):
                    return
                if (name.lower().endswith(".txt") or doc.mime_type == "text/plain") and doc.size <= MAX_TXT_BYTES:
                    data = await event.message.download_media(bytes)
                    text = (text + "\n" + data.decode("utf-8", errors="ignore")) if data else text

            if text.strip() or extra:
                await add_text(text, chat_id, extra)
        except Exception:
            log.exception("Handler error")

    async def handle_command(text: str, chat_id: int) -> None:
        parts = text.strip().split()
        cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/help"):
            await say(HELP, chat_id)
        elif cmd == "/stats":
            await say(
                reports.stats_text(
                    database.counts(), joiner.current, joiner.flood_remaining, joiner.delay, joiner.paused
                ),
                chat_id,
            )
        elif cmd == "/report":
            database.set_meta("notify_chat", chat_id)
            await send_final_report()
        elif cmd == "/pause":
            joiner.paused = True
            await say("⏸ Paused. Current link will finish; use /resume to continue.", chat_id)
        elif cmd == "/resume":
            joiner.paused = False
            if database.counts()[D.PENDING]:
                database.set_meta("batch_active", "1")
            joiner.kick()
            await say("▶️ Resumed.", chat_id)
        elif cmd == "/retry":
            n = database.retry_failed()
            if n:
                database.set_meta("batch_active", "1")
                database.set_meta("notify_chat", chat_id)
            joiner.kick()
            await say(f"🔁 Re-queued {n} failed link(s).", chat_id)
        elif cmd == "/delay":
            try:
                joiner.set_delay(float(parts[1]))
                await say(f"Base delay set to {joiner.delay:.1f}s", chat_id)
            except (IndexError, ValueError):
                await say("Usage: /delay 1.5", chat_id)

    # resume pending work after a restart
    c = database.counts()
    if c[D.PENDING] + c[D.PROCESSING] > 0:
        database.set_meta("batch_active", "1")
        await notify(
            f"♻️ Restarted - resuming {c[D.PENDING] + c[D.PROCESSING]} pending link(s) "
            f"({c[D.JOINED]} already joined, none are repeated)."
        )
    else:
        log.info("Ready. Send links to your Saved Messages. /help for commands.")

    worker = asyncio.create_task(joiner.run_forever())
    try:
        await client.run_until_disconnected()
    finally:
        worker.cancel()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
