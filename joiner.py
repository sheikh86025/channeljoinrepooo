"""Core worker: links ko ek-ek karke join karta hai, tab tak jab tak queue khatam na ho."""
import asyncio
import logging
import random
import time

from telethon import errors as E
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from db import row_url

log = logging.getLogger("joiner")


class _Never(Exception):
    """Placeholder agar telethon version me koi error class na ho."""


def _errs(*names):
    return tuple(getattr(E, n, _Never) for n in names)


FLOOD = _errs("FloodWaitError")
ALREADY = _errs("UserAlreadyParticipantError")
REQ_SENT = _errs("InviteRequestSentError")
TOO_MUCH = _errs("ChannelsTooMuchError")
FATAL = _errs("SessionRevokedError", "AuthKeyUnregisteredError", "UserDeactivatedError",
              "UserDeactivatedBanError", "SessionExpiredError", "AuthKeyDuplicatedError")
TRANSIENT = _errs("RpcCallFailError", "RpcMcgetFailError", "TimeoutError", "ServerError") + (
    asyncio.TimeoutError, ConnectionError, OSError)

PERMANENT = {
    "InviteHashExpiredError": "Invite link expire/revoked ho chuka hai",
    "InviteHashInvalidError": "Invite link galat hai",
    "InviteHashEmptyError": "Invite link khali/galat hai",
    "UsernameInvalidError": "Username galat hai",
    "UsernameNotOccupiedError": "Username exist nahi karta (channel delete/rename)",
    "ChannelPrivateError": "Channel private hai / ban hai / delete ho gaya",
    "ChannelInvalidError": "Channel invalid hai",
    "UserBannedInChannelError": "Aapka account is channel me banned hai",
    "UsersTooMuchError": "Group full hai (member limit)",
    "ChatInvalidError": "Chat invalid hai",
    "InviteRequestSentError": "Join request bheji gayi",
}
PERMANENT_TYPES = _errs(*PERMANENT.keys())


def fmt_secs(s):
    s = int(s)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _title(upd):
    chats = getattr(upd, "chats", None) or []
    return getattr(chats[0], "title", "") if chats else ""


class Joiner:
    def __init__(self, client, db, cfg, notifier):
        self.client, self.db, self.cfg, self.n = client, db, cfg, notifier
        self.paused = False
        self.fatal = False
        self.wake = asyncio.Event()
        self.idle = asyncio.Event()
        self.batch = None
        self.delay_factor = 1.0
        self.success_streak = 0
        self.flood_until = 0.0
        self.flood_hits = 0
        self._stop = False
        self.current = ""
        self.last_joined = ""

    # ---------- control ----------
    def wake_up(self):
        self.wake.set()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        self.wake.set()

    def stop(self):
        self._stop = True
        self.wake.set()

    async def _wait_wake(self):
        try:
            await asyncio.wait_for(self.wake.wait(), self.cfg.idle_wait)
        except asyncio.TimeoutError:
            pass
        self.wake.clear()

    async def _sleep(self, secs):
        await asyncio.sleep(secs)

    async def _delay(self):
        d = random.uniform(self.cfg.delay_min, self.cfg.delay_max) * self.delay_factor
        if d > 0:
            await self._sleep(d)

    # ---------- main loop ----------
    async def run(self):
        while not self._stop:
            if self.paused or self.fatal:
                await self._wait_wake()
                continue
            row = self.db.next_pending()
            if row is None:
                if self.batch:
                    await self._finish_batch()
                self.idle.set()
                await self._wait_wake()
                continue
            self.idle.clear()
            if not self.batch:
                await self._start_batch()
            await self.process(row)
            if not self.paused and not self.fatal and self.db.next_pending() is not None:
                await self._delay()

    # ---------- one link ----------
    async def _join(self, row):
        if row["kind"] == "invite":
            upd = await self.client(ImportChatInviteRequest(row["key"]))
        else:
            upd = await self.client(JoinChannelRequest(row["key"]))
        return _title(upd)

    async def process(self, row):
        rid, url = row["id"], row_url(row)
        self.current = url
        status, detail, title = None, "", ""
        try:
            title = await self._join(row)
            status = "joined"
        except FLOOD as e:
            await self._flood(getattr(e, "seconds", 60))
            return  # link pending hi rehta hai, wait ke baad dobara try
        except ALREADY:
            status = "already"
        except REQ_SENT:
            status = "request_sent"
        except TOO_MUCH:
            self.paused = True
            c = self.db.counts()
            await self.n.text(
                "🚫 Account ki channel/group limit poori ho gayi (ChannelsTooMuch).\n"
                "Normal account ~500, Premium ~1000 tak. Joining PAUSE kar di hai.\n"
                f"Pending links safe hain: {c['pending']}\n"
                "Kuch channels leave karo ya doosra account use karo, phir /resume bhejo."
            )
            return
        except FATAL as e:
            self.fatal = True
            log.error("Session unusable: %s", type(e).__name__)
            await self.n.text(f"🚫 Session/account problem: {type(e).__name__}\n"
                              "Naya SESSION_STRING banao aur Railway me update karo.")
            return
        except PERMANENT_TYPES as e:
            status, detail = "failed", PERMANENT.get(type(e).__name__, type(e).__name__)
        except (ValueError, TypeError):
            status, detail = "failed", "Link invalid hai ya channel/group nahi hai (user/bot ho sakta hai)"
        except TRANSIENT as e:
            tries = self.db.bump_attempt(rid, type(e).__name__)
            if tries >= self.cfg.max_attempts:
                status, detail = "failed", f"Telegram/network error {tries} baar: {type(e).__name__}"
            else:
                await self._sleep(min(5 * tries, 30))
                return
        except E.RPCError as e:
            tries = self.db.bump_attempt(rid, type(e).__name__)
            if tries >= self.cfg.max_attempts:
                status, detail = "failed", f"{type(e).__name__}: {e}"[:200]
            else:
                await self._sleep(min(5 * tries, 30))
                return

        self.db.mark(rid, status, detail, title)
        if status == "joined":
            self.last_joined = title or url
        await self._record(status, url, detail, title)

    async def _flood(self, seconds):
        wait = int(seconds) + 2
        self.flood_hits += 1
        self.delay_factor = min(self.delay_factor * 1.5, self.cfg.max_delay_factor)
        self.success_streak = 0
        self.flood_until = time.time() + wait
        log.warning("FloodWait %ss (delay factor now %.1f)", wait, self.delay_factor)
        if wait >= self.cfg.flood_notify_min:
            c = self.db.counts()
            await self.n.text(f"⏳ Telegram FloodWait: {fmt_secs(wait)} rukna padega.\n"
                              f"Apne aap continue hoga. Pending: {c['pending']}")
        await self._sleep(wait)
        self.flood_until = 0.0

    # ---------- batch reporting ----------
    async def _start_batch(self):
        pending = self.db.pending_count()
        self.batch = {"start": time.time(), "joined": 0, "already": 0, "request_sent": 0,
                      "failed": [], "done": 0}
        await self.n.text(f"▶️ Joining shuru. Queue: {pending} links")

    async def _record(self, status, url, detail, title):
        b = self.batch
        if b is None:
            return
        b["done"] += 1
        if status == "failed":
            b["failed"].append((url, detail))
            self.success_streak = 0
            if self.cfg.notify_each_fail:
                await self.n.text(f"❌ Join nahi hua\n{url}\nWajah: {detail}")
        else:
            b[status] += 1
            self.success_streak += 1
            if self.success_streak >= 20 and self.delay_factor > 1.0:
                self.delay_factor = max(1.0, self.delay_factor / 1.2)
                self.success_streak = 0
        pe = self.cfg.progress_every
        if pe and b["done"] % pe == 0:
            left = self.db.pending_count()
            if left:
                await self.n.text(f"📊 {b['done']} done | ✅ {b['joined']} joined | "
                                  f"❌ {len(b['failed'])} failed | ⏳ {left} baaki")

    async def _finish_batch(self):
        b, self.batch = self.batch, None
        took = time.time() - b["start"]
        lines = [
            "🏁 Sab links process ho gaye",
            f"Total: {b['done']}  (time {fmt_secs(took)})",
            f"✅ Joined: {b['joined']}",
            f"☑️ Already joined: {b['already']}",
            f"📨 Join request bheji: {b['request_sent']}",
            f"❌ Failed: {len(b['failed'])}",
        ]
        if b["failed"]:
            body = "\n".join(f"{u} — {d}" for u, d in b["failed"])
            if len(b["failed"]) <= 25:
                lines += ["", "Failed links:", body]
            else:
                await self.n.file("failed_links.txt", body.encode(), "Failed links list")
        await self.n.text("\n".join(lines))

    # ---------- status ----------
    def status_text(self):
        c = self.db.counts()
        avg = (self.cfg.delay_min + self.cfg.delay_max) / 2 * self.delay_factor
        if self.fatal:
            state = "🛑 STOPPED (session problem)"
        elif self.paused:
            state = "⏸ Paused"
        elif self.flood_until > time.time():
            state = f"⏳ FloodWait ({fmt_secs(self.flood_until - time.time())} baaki)"
        elif c["pending"]:
            state = "▶️ Joining chal rahi hai"
        else:
            state = "😴 Idle (queue khali)"
        eta = f"\nAnumaan: ~{fmt_secs(c['pending'] * (avg + 1))} (FloodWait chhodke)" if c["pending"] and not self.paused else ""
        return (f"{state}\n"
                f"⏳ Pending: {c['pending']}\n"
                f"✅ Joined: {c['joined']}\n"
                f"☑️ Already: {c['already']}\n"
                f"📨 Request sent: {c['request_sent']}\n"
                f"❌ Failed: {c['failed']}\n"
                f"{('Abhi: ' + self.current + chr(10)) if c['pending'] and self.current and not self.paused else ''}"
                f"{('Last joined: ' + self.last_joined + chr(10)) if self.last_joined else ''}"
                f"Delay: {self.cfg.delay_min:g}-{self.cfg.delay_max:g}s x{self.delay_factor:.1f} | "
                f"FloodWaits: {self.flood_hits}{eta}")
