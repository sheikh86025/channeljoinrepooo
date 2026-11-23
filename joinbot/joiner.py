"""The join worker: sequential, fast, FloodWait-proof, resumable."""
import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional, Tuple

from telethon import errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel, User

from . import db as D
from .config import Config
from .parser import INVITE, ParsedLink, local_validation_error

log = logging.getLogger("joinbot.joiner")

Notify = Callable[[str], Awaitable[None]]
Finish = Callable[[], Awaitable[None]]


class Joiner:
    def __init__(self, client, database: D.Database, cfg: Config, notify: Notify, on_finish: Finish):
        self.client = client
        self.db = database
        self.cfg = cfg
        self.notify = notify
        self.on_finish = on_finish
        self.wakeup = asyncio.Event()
        self.paused = False
        self.current = None  # sqlite row being processed
        self.flood_until = 0.0
        self.delay = cfg.join_delay
        self._ok_streak = 0

    # ------------------------------------------------------------ public
    def kick(self) -> None:
        self.wakeup.set()

    def set_delay(self, seconds: float) -> None:
        self.cfg.join_delay = max(0.0, seconds)
        self.delay = self.cfg.join_delay

    @property
    def flood_remaining(self) -> int:
        return max(0, int(self.flood_until - time.time()))

    async def run_forever(self) -> None:
        """Supervisor: the worker is restarted if anything unexpected happens."""
        while True:
            try:
                await self._run()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Worker crashed, restarting in 5s")
                self.current = None
                await asyncio.sleep(5)

    # ------------------------------------------------------------ worker
    async def _run(self) -> None:
        n = self.db.reset_processing()
        if n:
            log.info("Reset %d interrupted link(s) to pending", n)
        while True:
            row = None if self.paused else self.db.next_pending()
            if row is None:
                await self._idle()
                continue
            await self._process(row)

    async def _idle(self) -> None:
        """Nothing to do: send final report once, then sleep until kicked."""
        c = self.db.counts()
        if (
            not self.paused
            and self.db.get_meta("batch_active") == "1"
            and c[D.PENDING] == 0
            and c[D.PROCESSING] == 0
        ):
            # debounce: more links may still be arriving in further messages
            self.wakeup.clear()
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.cfg.finish_debounce)
                return  # new work / command arrived
            except asyncio.TimeoutError:
                pass
            if self.db.counts()[D.PENDING] == 0 and self.db.get_meta("batch_active") == "1":
                self.db.set_meta("batch_active", "0")
                try:
                    await self.on_finish()
                except Exception:
                    log.exception("Failed to send final report")
            return
        self.wakeup.clear()
        try:
            await asyncio.wait_for(self.wakeup.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass

    async def _process(self, row) -> None:
        self.current = row
        self.db.set_status(row["id"], D.PROCESSING)
        link = ParsedLink(row["kind"], row["ref"], row["key"], row["original"])
        network_retries = 0
        used_api = True
        try:
            while True:
                try:
                    err = local_validation_error(link)
                    if err:
                        status, detail, used_api = D.INVALID, err, False
                    else:
                        status, detail = await self._join(link)
                    break
                except errors.FloodWaitError as e:
                    await self._flood(int(getattr(e, "seconds", 30)))
                    continue  # retry the SAME link after the wait
                except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                    network_retries += 1
                    if network_retries > 5:
                        status, detail = D.ERROR, f"Network error: {e!r}"
                        break
                    await asyncio.sleep(min(30, 2 ** network_retries))
                except (errors.ChannelsTooMuchError, errors.UserChannelsTooMuchError):
                    # Account limit reached: put the link back and stop cleanly.
                    self.db.set_status(row["id"], D.PENDING, "")
                    self.paused = True
                    await self.notify(
                        "⛔ Channel limit reached on this account (Telegram allows a limited number "
                        "of joined channels). Joining is PAUSED. Leave some channels, then send /resume."
                    )
                    return
                except Exception as e:  # unknown error: record and move on
                    log.exception("Unexpected error for %s", link.original)
                    status, detail = D.ERROR, f"{type(e).__name__}: {e}"
                    break
            self.db.set_status(row["id"], status, detail)
            log.info("%s -> %s %s", link.original, status, detail)
            if status in (D.JOINED, D.ALREADY, D.REQUEST_SENT):
                self._on_success()
        finally:
            self.current = None
        if used_api and self.delay > 0:
            await asyncio.sleep(self.delay)

    # ------------------------------------------------------------ helpers
    def _on_success(self) -> None:
        self._ok_streak += 1
        if self._ok_streak >= 10 and self.delay > self.cfg.join_delay:
            self.delay = max(self.cfg.join_delay, self.delay * 0.8)
            self._ok_streak = 0

    async def _flood(self, seconds: int) -> None:
        wait = seconds + 1
        self.flood_until = time.time() + wait
        self._ok_streak = 0
        # adaptive back-off so we hit FloodWait less often afterwards
        self.delay = min(self.cfg.max_delay, max(self.delay * 1.5, self.cfg.join_delay + 0.5))
        log.warning("FloodWait %ss - sleeping", wait)
        if wait >= self.cfg.flood_notify_min:
            resume = time.strftime("%H:%M:%S", time.localtime(self.flood_until))
            await self.notify(f"🌊 FloodWait {wait}s. Auto-resuming at ~{resume}. No action needed.")
        try:
            await asyncio.sleep(wait)
        finally:
            self.flood_until = 0.0

    async def _join(self, link: ParsedLink) -> Tuple[str, str]:
        """One join attempt. FloodWaitError & transient errors propagate to caller."""
        try:
            if link.kind == INVITE:
                await self.client(ImportChatInviteRequest(link.ref))
                return D.JOINED, ""
            return await self._join_public(link.ref)
        except errors.UserAlreadyParticipantError:
            return D.ALREADY, ""
        except errors.InviteRequestSentError:
            return D.REQUEST_SENT, "Admin approval required"
        except (errors.InviteHashInvalidError, errors.InviteHashEmptyError):
            return D.INVALID, "Invalid invite link"
        except errors.InviteHashExpiredError:
            return D.EXPIRED, "Invite expired or revoked"
        except errors.ChannelPrivateError:
            return D.EXPIRED, "Private channel / no access"
        except (errors.UsernameInvalidError,):
            return D.INVALID, "Invalid username"
        except (errors.UsernameNotOccupiedError,):
            return D.NOT_FOUND, "Username does not exist"
        except errors.UserBannedInChannelError:
            return D.ERROR, "Banned from this channel"

    async def _join_public(self, username: str) -> Tuple[str, str]:
        try:
            ent = await self.client.get_entity(username)
        except ValueError:
            return D.NOT_FOUND, "Username does not exist"
        if isinstance(ent, User):
            return D.ERROR, "This is a user/bot, not a channel or group"
        if not isinstance(ent, Channel):
            return D.ERROR, "Not a joinable channel/group"
        if getattr(ent, "left", True) is False:
            return D.ALREADY, ""
        await self.client(JoinChannelRequest(ent))
        return D.JOINED, ""
