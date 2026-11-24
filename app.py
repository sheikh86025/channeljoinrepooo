"""Control bot + userbot manager: status, buttons, /login, queue."""
import asyncio
import io
import logging
import re
import time

from telethon import errors as E

from joiner import Joiner, _errs
from linkparser import extract_links
from db import row_url

log = logging.getLogger("app")

NEED_2FA = _errs("SessionPasswordNeededError")
CODE_BAD = _errs("PhoneCodeInvalidError", "PhoneCodeEmptyError")
CODE_EXP = _errs("PhoneCodeExpiredError")
PW_BAD = _errs("PasswordHashInvalidError")
PHONE_BAD = _errs("PhoneNumberInvalidError", "PhoneNumberBannedError", "PhoneNumberUnoccupiedError")
FLOOD = _errs("FloodWaitError")

HELP = (
    "🤖 Channel Joiner\n\n"
    "Links bhejo (text ya .txt file) → userbot ek-ek karke sab join karega.\n\n"
    "/status — progress dekho\n"
    "/live — auto-update hone wala status\n"
    "/pause  /resume — roko / chalao\n"
    "/failed — jo join nahi hue\n"
    "/retry — failed dobara try\n"
    "/export — joined/failed/pending .txt files\n"
    "/delay 3 6 — join delay (sec)\n"
    "/clear — finished records saaf (pending safe)\n"
    "/login — account login (OTP se)\n"
    "/logout — account logout\n"
    "/cancel — login beech me roko"
)


async def connect_with_retry(client, tries=6):
    for i in range(tries):
        try:
            await client.connect()
            return
        except Exception as e:
            wait = min(5 * 2 ** i, 60)
            log.warning("connect failed (%s), retry in %ss", type(e).__name__, wait)
            await asyncio.sleep(wait)
    raise ConnectionError("Telegram se connect nahi ho paya")


class BotNotifier:
    """Owner ko bot ke through message/file bhejta hai."""

    def __init__(self, bot, get_owner):
        self.bot, self.get_owner = bot, get_owner

    async def _send(self, factory):
        for _ in range(2):
            try:
                return await factory()
            except FLOOD as e:
                if getattr(e, "seconds", 999) > 300:
                    return None
                await asyncio.sleep(e.seconds + 1)
            except Exception:
                log.exception("notify failed")
                return None

    async def text(self, msg, buttons=None):
        owner = self.get_owner()
        if owner:
            return await self._send(lambda: self.bot.send_message(owner, msg[:3900], link_preview=False, buttons=buttons))

    async def file(self, name, data, caption=""):
        owner = self.get_owner()
        if owner:
            def make():
                bio = io.BytesIO(data)
                bio.name = name
                return self.bot.send_file(owner, bio, caption=caption)
            return await self._send(make)


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


class App:
    def __init__(self, cfg, db, bot, client_factory=None):
        self.cfg, self.db, self.bot = cfg, db, bot
        self.factory = client_factory or self._default_factory
        self.notifier = BotNotifier(bot, lambda: self.owner)
        self.user = self.joiner = self.worker = None
        self.login = None
        self.live_task = None

    # ---------- helpers ----------
    def _default_factory(self, session_str):
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        return TelegramClient(StringSession(session_str), self.cfg.api_id, self.cfg.api_hash,
                              flood_sleep_threshold=0, connection_retries=-1,
                              retry_delay=3, auto_reconnect=True)

    @property
    def owner(self):
        if self.cfg.owner_id:
            return self.cfg.owner_id
        v = self.db.get("owner")
        return int(v) if v else 0

    def kb(self):
        from telethon import Button
        return [[Button.inline("📊 Status", b"st"), Button.inline("📤 Export", b"export")],
                [Button.inline("⏸ Pause", b"pause"), Button.inline("▶️ Resume", b"resume")],
                [Button.inline("❌ Failed", b"failed"), Button.inline("🔁 Retry failed", b"retry")]]

    def status_text(self):
        if self.joiner:
            base = self.joiner.status_text()
        else:
            base = f"🔒 Userbot login nahi hai (/login)\n⏳ Pending: {self.db.pending_count()}"
        return base + f"\n🕐 Last 24h joined: {self.db.count_since('joined', time.time() - 86400)}"

    # ---------- userbot lifecycle ----------
    async def start_userbot(self, session):
        await self.stop_userbot()
        try:
            client = self.factory(session)
        except ValueError:
            return False, "SESSION_STRING format galat hai (Telethon string chahiye). /login use karo."
        try:
            await connect_with_retry(client)
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, "Session expire/logout ho chuka hai. /login karo."
            me = await client.get_me()
        except Exception as e:
            return False, f"connect error: {type(e).__name__}"
        self.user = client
        self.joiner = Joiner(client, self.db, self.cfg, self.notifier)
        self.worker = asyncio.create_task(supervise(self.joiner))
        name = ((getattr(me, "first_name", "") or "") + (" @" + me.username if getattr(me, "username", None) else "")).strip()
        return True, name or "account"

    async def stop_userbot(self):
        if self.joiner:
            self.joiner.stop()
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except (asyncio.CancelledError, Exception):
                pass
        if self.user:
            try:
                await self.user.disconnect()
            except Exception:
                pass
        self.user = self.joiner = self.worker = None

    async def boot(self):
        session = self.db.get("session") or self.cfg.session_string
        n = self.notifier
        if not session:
            await n.text("👋 Bot online. Userbot login nahi hai → /login bhejo.\n\n" + HELP, buttons=self.kb())
            return
        ok, info = await self.start_userbot(session)
        if ok:
            p = self.db.pending_count()
            await n.text(f"✅ Userbot online: {info}" + (f"\nPending {p} links se resume ho raha hai." if p else "\n/help dekho."),
                         buttons=self.kb())
        else:
            await n.text(f"⚠️ Userbot start nahi hua: {info}")

    # ---------- incoming ----------
    async def on_message(self, event):
        uid = event.sender_id
        text = (event.raw_text or "").strip()
        if not self.owner:
            if text.lower().startswith("/start"):
                self.db.set("owner", str(uid))
                await self.notifier.text("✅ Aap is bot ke owner set ho gaye (sirf aap control kar sakte ho).\n\n" + HELP, buttons=self.kb())
                await self.boot()
            return
        if uid != self.owner:
            return
        try:
            cmd = text.split()[0].lower().split("@")[0] if text.startswith("/") else None
            if self.login and cmd is None:
                await self.login_step(event, text)
            elif cmd:
                await self.command(cmd, text.split(), event)
            else:
                await self.ingest(event, text)
        except Exception as e:
            log.exception("handler error")
            await self.notifier.text(f"⚠️ Internal error: {type(e).__name__}")

    async def on_callback(self, event):
        if event.sender_id != self.owner:
            return
        d = event.data.decode()
        try:
            if d == "st":
                try:
                    await event.edit(self.status_text(), buttons=self.kb())
                except Exception:
                    pass
            else:
                await self.command("/" + d, ["/" + d], None)
        finally:
            try:
                await event.answer()
            except Exception:
                pass

    async def ingest(self, event, text):
        f = getattr(event.message, "file", None)
        if f is not None:
            name = (getattr(f, "name", "") or "").lower()
            mime = getattr(f, "mime_type", "") or ""
            size = getattr(f, "size", 0) or 0
            if (name.endswith((".txt", ".csv")) or mime.startswith("text/")) and size <= 5_000_000:
                data = await event.message.download_media(file=bytes)
                text += "\n" + data.decode("utf-8", "ignore")
        items = extract_links(text)
        if not items:
            await self.notifier.text("Koi Telegram link nahi mila. /help dekho.")
            return
        new, req, dup = self.db.add_links(items)
        warn = "" if self.joiner else "\n⚠️ Userbot login nahi hai — /login karo. Links queue me safe hain."
        await self.notifier.text(f"📥 {new} naye links queue me | {req} failed wale dobara | {dup} duplicate skip\n"
                                 f"Pending: {self.db.pending_count()}{warn}")
        if self.joiner:
            self.joiner.wake_up()

    # ---------- commands ----------
    async def command(self, cmd, parts, event):
        n, db, j = self.notifier, self.db, self.joiner
        if cmd in ("/start", "/help"):
            await n.text(HELP, buttons=self.kb())
        elif cmd == "/status":
            await n.text(self.status_text(), buttons=self.kb())
        elif cmd == "/live":
            await self.start_live()
        elif cmd in ("/pause", "/resume"):
            if not j:
                await n.text("Userbot login nahi hai. /login karo.")
            elif cmd == "/pause":
                j.pause()
                await n.text("⏸ Pause kar diya. /resume se continue.")
            elif j.fatal:
                await n.text("Session problem hai. /login se dobara login karo.")
            else:
                j.resume()
                await n.text(f"▶️ Resume. Pending: {db.pending_count()}")
        elif cmd == "/failed":
            rows = db.failed_rows()
            if not rows:
                await n.text("Koi failed link nahi 🎉")
            else:
                body = "\n".join(f"{row_url(r)} — {r['detail']}" for r in rows)
                if len(rows) <= 25:
                    await n.text(f"❌ Failed ({len(rows)}):\n{body}")
                else:
                    await n.file("failed_links.txt", body.encode(), f"❌ Failed ({len(rows)})")
        elif cmd == "/retry":
            k = db.requeue_failed()
            if j:
                j.wake_up()
            await n.text(f"🔁 {k} failed links dobara queue me daale")
        elif cmd == "/export":
            sent = 0
            for st in ("joined", "request_sent", "already", "failed", "pending"):
                rows = db.rows_by_status(st)
                if rows:
                    body = "\n".join(f"{row_url(r)} — {r['title'] or r['detail'] or ''}".rstrip(" —") for r in rows)
                    await n.file(f"{st}.txt", body.encode(), f"{st}: {len(rows)}")
                    sent += 1
            if not sent:
                await n.text("Abhi kuch export karne ko nahi hai.")
        elif cmd == "/clear":
            await n.text(f"🧹 {db.clear_finished()} finished records hata diye. Pending safe hain.")
        elif cmd == "/delay":
            try:
                lo = float(parts[1])
                hi = float(parts[2]) if len(parts) > 2 else lo
                if lo < 0 or hi < lo:
                    raise ValueError
                self.cfg.delay_min, self.cfg.delay_max = lo, hi
                await n.text(f"Delay ab {lo:g}-{hi:g}s")
            except (IndexError, ValueError):
                await n.text("Use: /delay 3 6")
        elif cmd == "/login":
            await self.login_begin()
        elif cmd == "/cancel":
            if self.login:
                await self._cancel_login()
                await n.text("Login cancel.")
            else:
                await n.text("Cancel karne ko kuch nahi.")
        elif cmd == "/logout":
            await self.logout()
        else:
            await n.text("Command samajh nahi aaya. /help dekho.")

    async def start_live(self):
        if self.live_task:
            self.live_task.cancel()
        owner = self.owner
        last = self.status_text()
        m = await self.bot.send_message(owner, last)

        async def loop():
            nonlocal last
            end = time.time() + 3600
            try:
                while time.time() < end:
                    await asyncio.sleep(6)
                    t = self.status_text()
                    if t != last:
                        last = t
                        try:
                            await m.edit(t)
                        except Exception:
                            pass
                    if not (self.joiner and (self.db.pending_count() or self.joiner.paused)):
                        break
            except asyncio.CancelledError:
                pass

        self.live_task = asyncio.create_task(loop())

    # ---------- login via bot ----------
    async def login_begin(self):
        await self._cancel_login()
        self.login = {"step": "phone"}
        await self.notifier.text("📱 Apna phone number bhejo country code ke saath, jaise +919876543210\n/cancel se roko.")

    async def _cancel_login(self):
        st, self.login = self.login, None
        if st and st.get("client"):
            try:
                await st["client"].disconnect()
            except Exception:
                pass

    async def _try_delete(self, event):
        try:
            await event.delete()
        except Exception:
            pass

    async def login_step(self, event, text):
        st, n = self.login, self.notifier
        try:
            if st["step"] == "phone":
                phone = re.sub(r"[^\d+]", "", text)
                if not phone.startswith("+") or len(phone) < 8:
                    await n.text("Number + ke saath bhejo, jaise +919876543210")
                    return
                client = self.factory("")
                await connect_with_retry(client)
                st["client"] = client
                sent = await client.send_code_request(phone)
                st.update(step="code", phone=phone, hash=sent.phone_code_hash)
                await n.text("📨 OTP Telegram app me aaya hoga ('Telegram' naam ki chat me).\n"
                             "⚠️ OTP DASHES ke saath bhejo: 1-2-3-4-5\n"
                             "(seedha bhejoge to Telegram code cancel kar deta hai)")
            elif st["step"] == "code":
                code = re.sub(r"\D", "", text)
                await self._try_delete(event)
                try:
                    await st["client"].sign_in(st["phone"], code, phone_code_hash=st["hash"])
                except NEED_2FA:
                    st["step"] = "password"
                    await n.text("🔐 Aapka 2-step verification password bhejo.")
                    return
                await self._login_done()
            elif st["step"] == "password":
                await self._try_delete(event)
                await st["client"].sign_in(password=text)
                await self._login_done()
        except PHONE_BAD:
            await self._cancel_login()
            await n.text("❌ Phone number galat/banned hai. /login se dobara try karo.")
        except CODE_BAD:
            await n.text("❌ Code galat hai. Dashes ke saath dobara bhejo (1-2-3-4-5), ya /cancel.")
        except CODE_EXP:
            await self._cancel_login()
            await n.text("⌛ Code expire ho gaya. /login se dobara shuru karo.")
        except PW_BAD:
            await n.text("❌ Password galat hai. Dobara bhejo, ya /cancel.")
        except FLOOD as e:
            await self._cancel_login()
            await n.text(f"⏳ Telegram ne {getattr(e, 'seconds', '?')} sec ruk ne ko kaha. Baad me /login karo.")
        except Exception as e:
            log.exception("login error")
            await self._cancel_login()
            await n.text(f"❌ Login error: {type(e).__name__}. /login se dobara try karo.")

    async def _login_done(self):
        st, self.login = self.login, None
        client = st["client"]
        session = client.session.save()
        await client.disconnect()
        self.db.set("session", session)
        ok, info = await self.start_userbot(session)
        if ok:
            p = self.db.pending_count()
            await self.notifier.text(f"✅ Login ho gaya: {info}\nAb links bhejo." +
                                     (f"\nQueue me {p} pending links hain, shuru ho rahi hain." if p else ""),
                                     buttons=self.kb())
        else:
            await self.notifier.text(f"⚠️ Login hua par userbot start nahi hua: {info}")

    async def logout(self):
        if self.login:
            await self._cancel_login()
        if not self.user:
            self.db.delete("session")
            await self.notifier.text("Userbot pehle se logout hai.")
            return
        client = self.user
        await self.stop_userbot()
        try:
            await client.connect()
            await client.log_out()
        except Exception:
            pass
        self.db.delete("session")
        await self.notifier.text("👋 Logout ho gaya (session Telegram se bhi hata diya). Dobara /login se aa sakte ho.")


def register(bot, app):
    from telethon import events

    @bot.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def _on_msg(event):
        await app.on_message(event)

    @bot.on(events.CallbackQuery)
    async def _on_cb(event):
        await app.on_callback(event)
