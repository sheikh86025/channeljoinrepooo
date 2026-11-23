"""Tests. The Telethon dependency is stubbed so these run anywhere:
parser, SQLite persistence/resume, reports, and the join worker
(FloodWait auto-resume, invalid links not stopping the run, final report)."""
import asyncio
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------- telethon stub
def _install_stub():
    if "telethon_real_present" in sys.modules:
        return
    err = types.ModuleType("telethon.errors")

    class FloodWaitError(Exception):
        def __init__(self, seconds):
            self.seconds = seconds

    for name in [
        "UserAlreadyParticipantError", "InviteRequestSentError", "InviteHashInvalidError",
        "InviteHashEmptyError", "InviteHashExpiredError", "ChannelPrivateError",
        "UsernameInvalidError", "UsernameNotOccupiedError", "UserBannedInChannelError",
        "ChannelsTooMuchError", "UserChannelsTooMuchError",
    ]:
        setattr(err, name, type(name, (Exception,), {}))
    err.FloodWaitError = FloodWaitError

    tl_types = types.ModuleType("telethon.tl.types")
    tl_types.Channel = type("Channel", (), {})
    tl_types.User = type("User", (), {})
    ch = types.ModuleType("telethon.tl.functions.channels")
    ch.JoinChannelRequest = lambda e: ("join", e)
    ms = types.ModuleType("telethon.tl.functions.messages")
    ms.ImportChatInviteRequest = lambda h: ("invite", h)
    mods = {
        "telethon": types.ModuleType("telethon"),
        "telethon.errors": err,
        "telethon.tl": types.ModuleType("telethon.tl"),
        "telethon.tl.functions": types.ModuleType("telethon.tl.functions"),
        "telethon.tl.functions.channels": ch,
        "telethon.tl.functions.messages": ms,
        "telethon.tl.types": tl_types,
    }
    mods["telethon"].errors = err
    sys.modules.update(mods)


_install_stub()

from joinbot import db as D  # noqa: E402
from joinbot import reports  # noqa: E402
from joinbot.config import Config  # noqa: E402
from joinbot.joiner import Joiner  # noqa: E402
from joinbot.parser import extract_links, local_validation_error  # noqa: E402
from telethon import errors  # noqa: E402

HASH = "AAAAAAAAAAAAAAAAAAAAAA"


class ParserTests(unittest.TestCase):
    def test_formats_and_dedupe(self):
        text = (
            f"https://t.me/+{HASH} t.me/joinchat/BBBBBBBBBBBBBBBBBBBBBB\n"
            "https://t.me/durov @DurovChannel t.me/durov/55 tg://resolve?domain=other_chan\n"
            "mail me a@gmail.com https://t.me/c/123/4 https://t.me/addstickers/x"
        )
        links = extract_links(text)
        keys = [l.key for l in links]
        self.assertEqual(keys, [f"i:{HASH}", "i:BBBBBBBBBBBBBBBBBBBBBB", "u:durov",
                                "u:durovchannel", "u:other_chan"])

    def test_hidden_urls(self):
        self.assertEqual(len(extract_links("click here", [f"https://t.me/+{HASH}"])), 1)

    def test_local_validation(self):
        self.assertIsNotNone(local_validation_error(extract_links("t.me/+short")[0]))
        self.assertIsNotNone(local_validation_error(extract_links("t.me/abc")[0]))
        self.assertIsNone(local_validation_error(extract_links(f"t.me/+{HASH}")[0]))


class DbTests(unittest.TestCase):
    def test_resume_and_dedupe(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "x.db")
            db = D.Database(p)
            links = extract_links(f"t.me/+{HASH} t.me/channelone")
            self.assertEqual(db.add_links(links), (2, 0))
            self.assertEqual(db.add_links(links), (0, 2))
            row = db.next_pending()
            db.set_status(row["id"], D.PROCESSING)
            db.set_status(row["id"], D.JOINED)
            nxt = db.next_pending()
            db.set_status(nxt["id"], D.PROCESSING)  # simulate crash mid-link
            db2 = D.Database(p)  # "restart"
            self.assertEqual(db2.reset_processing(), 1)
            c = db2.counts()
            self.assertEqual((c[D.JOINED], c[D.PENDING], c["total"]), (1, 1, 2))


class FakeClient:
    """Scripted client: behaviour per invite hash / username."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    async def __call__(self, req):
        kind, ref = req
        self.calls.append(ref)
        beh = self.script.get(ref if kind == "invite" else getattr(ref, "username", ref))
        if isinstance(beh, list):
            beh = beh.pop(0) if beh else None
        if isinstance(beh, Exception):
            raise beh
        return None

    async def get_entity(self, username):
        raise ValueError("not found")


class JoinerTests(unittest.TestCase):
    def test_full_run(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as t:
                h = [chr(65 + i) * 20 + "xy" for i in range(6)]  # 22-char hashes
                script = {
                    h[0]: None,                                   # joined
                    h[1]: errors.UserAlreadyParticipantError(),   # already
                    h[2]: errors.InviteHashExpiredError(),        # expired
                    h[3]: [errors.FloodWaitError(1), None],       # flood then joined
                    h[4]: errors.InviteRequestSentError(),        # request sent
                    h[5]: errors.InviteHashInvalidError(),        # invalid
                }
                client = FakeClient(script)
                db = D.Database(os.path.join(t, "j.db"))
                text = " ".join(f"https://t.me/+{x}" for x in h) + " t.me/bad"
                db.add_links(extract_links(text))
                db.set_meta("batch_active", "1")
                cfg = Config(api_id=1, api_hash="x", join_delay=0.0, finish_debounce=0.2,
                             reports_dir=os.path.join(t, "r"))
                msgs, finished = [], asyncio.Event()

                async def notify(m):
                    msgs.append(m)

                async def fin():
                    finished.set()

                j = Joiner(client, db, cfg, notify, fin)
                task = asyncio.create_task(j.run_forever())
                await asyncio.wait_for(finished.wait(), timeout=15)
                task.cancel()
                c = db.counts()
                self.assertEqual(c[D.JOINED], 2)
                self.assertEqual(c[D.ALREADY], 1)
                self.assertEqual(c[D.EXPIRED], 1)
                self.assertEqual(c[D.REQUEST_SENT], 1)
                self.assertEqual(c[D.INVALID], 2)  # bad hash + 'bad' (too short, local)
                self.assertEqual(c[D.PENDING], 0)
                self.assertEqual(client.calls.count(h[3]), 2)  # retried after FloodWait
                text, files = reports.build_report(db, cfg.reports_dir)
                self.assertIn("Join Requests Sent: 1", text)
                self.assertTrue(all(os.path.exists(f) for f in files))
                self.assertIn("Progress", reports.stats_text(c, None, 0, 1.0, False))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
