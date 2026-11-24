import asyncio
import logging
import time
from datetime import datetime, timezone

from reports import build_report, fmt_secs

log = logging.getLogger("joiner")

# Telethon error class ke naam -> (status, detail). Naam se match karte hain taaki
# worker Telegram library se independent rahe (aur test ho sake).
OUTCOME_BY_ERROR = {
    "UserAlreadyParticipantError": ("already_joined", ""),
    "InviteRequestSentError": ("request_sent", ""),
    "InviteHashExpiredError": ("expired", "invite expired / revoked"),
    "InviteHashInvalidError": ("invalid", "invalid invite link"),
    "InviteHashEmptyError": ("invalid", "empty invite link"),
    "ChannelPrivateError": ("expired", "private / banned / not accessible"),
    "ChannelInvalidError": ("not_found", "channel invalid"),
    "UsernameNotOccupiedError": ("not_found", "username not found"),
    "UsernameInvalidError": ("not_found", "username invalid"),
    "UserBannedInChannelError": ("failed", "account banned in this channel"),
}
LIMIT_ERRORS = {"ChannelsTooMuchError", "UserChannelsTooMuchError"}
FATAL_ERRORS = {
    "AuthKeyUnregisteredError", "AuthKeyDuplicatedError", "SessionRevokedError",
    "SessionExpiredError", "UserDeactivatedBanError", "UserDeactivatedError",
}
TRANSIENT = (OSError, asyncio.TimeoutError)


def flood_seconds(exc):
    """FloodWait ho to seconds, warna None."""
    for cls in type(exc).__mro__:
        if cls.__name__ in ("FloodWaitError", "FloodPremiumWaitError"):
            return int(getattr(exc, "seconds", 0) or 0)
    return None


def _clock(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M UTC")


class Worker:
    """Ek-ek link ko sequentially join karta hai, FloodWait par khud wait karke resume."""

    def __init__(self, cfg, db, ops, notify, send_report):
        self.cfg, self.db, self.ops = cfg, db, ops
        self.notify, self.send_report = notify, send_report
        self.delay = cfg.start_delay
        self.streak = 0
        self.paused = False
        self.force_resume = False
        self.limit_hit = False
        self.fatal = None
        self.last_add = 0.0
        self.last_flood_notice = 0.0
        self.next_report_try = 0.0
        # tunables (tests me chhote kiye jaate hain)
        self.flood_padding = 2
        self.idle_sleep = 2.0
        self.limit_poll = 5.0
        self.count_every = 120.0

    # ---- public helpers ----
    def notify_new_links(self):
        self.last_add = time.time()

    def status_label(self):
        if self.fatal:
            return f"❌ Account error: {self.fatal}"
        if self.limit_hit:
            return "🧹 Channel limit full — cleanup ka wait"
        if self.paused:
            return "⏸ Paused"
        return "▶️ Running"

    # ---- main loop ----
    async def run(self):
        await self._wait_flood_remaining()
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker tick failed — 5s baad dobara")
                await asyncio.sleep(5)

    async def _tick(self):
        if self.fatal:
            await asyncio.sleep(30)
            return
        if self.paused:
            await asyncio.sleep(self.idle_sleep)
            return
        row = self.db.next_pending()
        if row is None:
            await self._maybe_report()
            await asyncio.sleep(self.idle_sleep)
            return
        await self._handle(row)

    async def _handle(self, row):
        self.db.start(row["id"])
        try:
            res = await self.ops.join(row["kind"], row["val"])
        except Exception as exc:
            await self._on_error(row, exc)
            return
        self.db.finish(row["id"], res["status"], res.get("detail", ""),
                       res.get("title", ""), res.get("channel_id", ""))
        log.info("%s -> %s", row["url"], res["status"])
        self._ok_step()
        await asyncio.sleep(self.delay)

    async def _on_error(self, row, exc):
        name = type(exc).__name__
        secs = flood_seconds(exc)

        if secs is not None:  # FloodWait: link wapas queue me, wait, phir resume
            self.db.requeue(row["id"])
            await self._flood(secs)
            return
        if name in FATAL_ERRORS:
            self.db.requeue(row["id"])
            self.fatal = name
            log.error("fatal account error: %s", name)
            await self.notify(
                f"❌ Account error: {name}\nSession/account ka issue hai. Naya SESSION_STRING "
                f"banao ya account check karo. Progress DB me safe hai.")
            return
        if name in LIMIT_ERRORS:
            self.db.requeue(row["id"])
            await self._limit_wait()
            return
        if name in OUTCOME_BY_ERROR:
            status, detail = OUTCOME_BY_ERROR[name]
            self.db.finish(row["id"], status, detail)
            log.info("%s -> %s", row["url"], status)
            self._ok_step()
            await asyncio.sleep(self.delay)
            return
        if isinstance(exc, TRANSIENT):  # network hiccup: thodi der baad retry
            if row["attempts"] + 1 >= 3:
                self.db.finish(row["id"], "failed", f"network error: {name}")
            else:
                self.db.requeue(row["id"])
            await asyncio.sleep(5)
            return

        # baaki sab: ye link failed, process aage badhta hai
        self.db.finish(row["id"], "failed", f"{name}: {str(exc)[:150]}")
        log.warning("%s -> failed (%s)", row["url"], name)
        await asyncio.sleep(self.delay)

    # ---- adaptive speed ----
    def _ok_step(self):
        self.streak += 1
        if self.streak >= 8:  # 8 safe joins ke baad gap thoda kam
            self.streak = 0
            self.delay = max(self.cfg.min_delay, self.delay * 0.85)

    # ---- FloodWait ----
    async def _flood(self, secs):
        wait = secs + self.flood_padding
        until = time.time() + wait
        self.db.meta_set("flood_until", f"{until:.3f}")
        self.streak = 0
        self.delay = min(self.cfg.max_delay, max(self.delay * 1.5, self.cfg.start_delay))
        log.warning("FloodWait %ss — wait karke resume karunga", wait)
        now = time.time()
        if wait >= 60 and now - self.last_flood_notice > 300:
            self.last_flood_notice = now
            await self.notify(
                f"🌊 FloodWait: {fmt_secs(wait)}. Apne aap resume ho jayega ({_clock(until)} ke baad).")
        await self._sleep_until(until)
        self.db.meta_set("flood_until", "0")

    async def _wait_flood_remaining(self):
        until = float(self.db.meta_get("flood_until", "0") or 0)
        if until > time.time():
            log.info("restart ke baad bachi hui FloodWait ka wait")
            await self._sleep_until(until)
            self.db.meta_set("flood_until", "0")

    @staticmethod
    async def _sleep_until(ts):
        while True:
            left = ts - time.time()
            if left <= 0:
                return
            await asyncio.sleep(min(30, left))

    # ---- channel limit (500 / 1000) ----
    async def _safe_count(self):
        try:
            return await self.ops.count_joined()
        except Exception:
            return None

    async def _limit_wait(self):
        joined = await self._safe_count()
        self.limit_hit = True
        self.force_resume = False
        await self.notify(
            f"🧹 Channel limit full ({joined if joined is not None else '?'} joined).\n"
            f"Cleanup (leave) kar do — {self.cfg.min_free}+ channels chhodte hi main khud join "
            f"chalu kar dunga (ya /resume bhejo).\nBaaki links: {self.db.pending_count()}")
        waited = 0.0
        while not self.force_resume:
            await asyncio.sleep(self.limit_poll)
            waited += self.limit_poll
            if waited >= self.count_every:
                waited = 0.0
                now_count = await self._safe_count()
                if (now_count is not None and joined is not None
                        and now_count <= joined - self.cfg.min_free):
                    break
        self.limit_hit = False
        await self.notify("▶️ Joining dobara chalu.")

    # ---- final report ----
    async def _maybe_report(self):
        if not self.db.has_unreported():
            return
        now = time.time()
        if now - self.last_add < self.cfg.report_debounce or now < self.next_report_try:
            return
        text, files = build_report(self.db, batch_only=True, title="✅ Final Report")
        ok = await self.send_report(text, files)
        if ok:
            self.db.mark_reported()
        else:
            self.next_report_try = now + 60
