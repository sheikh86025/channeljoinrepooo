"""Telegram ke bina chalne wale tests (FakeOps use hota hai).
Run:  python -m unittest test_joiner -v
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from database import Database
from handlers import handle_links_text, run_command
from links import collect_text, extract_links
from reports import build_report, stats_text
from worker import Worker


# ---- Telethon jaise naam wale fake errors ----
class InviteHashExpiredError(Exception): pass
class InviteHashInvalidError(Exception): pass
class InviteRequestSentError(Exception): pass
class UserAlreadyParticipantError(Exception): pass
class UsernameNotOccupiedError(Exception): pass
class ChannelsTooMuchError(Exception): pass
class UserDeactivatedBanError(Exception): pass


class FloodWaitError(Exception):
    def __init__(self, seconds):
        super().__init__(f"wait {seconds}")
        self.seconds = seconds


def joined(val):
    return {"status": "joined", "title": val, "channel_id": "-100123"}


class FakeOps:
    def __init__(self, script=None, counts=(500,)):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls = []
        self.counts = list(counts)

    async def join(self, kind, val):
        self.calls.append(val)
        steps = self.script.get(val)
        step = steps.pop(0) if steps else joined(val)
        if isinstance(step, Exception):
            raise step
        return step

    async def count_joined(self):
        return self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]


def make_cfg():
    return Config(api_id=1, api_hash="x", bot_token="t", owner_id=1, session_string="s",
                  start_delay=0, min_delay=0, max_delay=0.01, min_free=20, report_debounce=0)


class Harness:
    def __init__(self, ops, db=None):
        self.db = db or Database(":memory:")
        self.notes, self.reports = [], []

        async def notify(text):
            self.notes.append(text)

        async def send_report(text, files):
            self.reports.append((text, files))
            return True

        self.worker = Worker(make_cfg(), self.db, ops, notify, send_report)
        self.worker.flood_padding = 0
        self.worker.idle_sleep = 0.01
        self.worker.limit_poll = 0.01
        self.worker.count_every = 0.03

    def add(self, text):
        return handle_links_text(self.db, self.worker, text)

    async def run_until_report(self, timeout=10):
        task = asyncio.create_task(self.worker.run())
        try:
            for _ in range(int(timeout / 0.02)):
                if self.reports:
                    return
                await asyncio.sleep(0.02)
            raise AssertionError("final report nahi aaya (timeout)")
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class ParserTests(unittest.TestCase):
    def test_formats_and_dedupe(self):
        text = """https://t.me/+AbCd1234 t.me/Deals_Hub @DealsHub
        https://t.me/deals_hub T.ME/DEALS_HUB t.me/joinchat/ZzZz999 https://t.me/+AbCd1234
        tg://join?invite=TgHash77 telegram.me/NewsFlash
        @solo_channel
        t.me/addlist/xyz t.me/c/123/45 bit.me/abcdef hello @ab foo@gmail.com"""
        links, repeats = extract_links(text)
        got = [(k, v) for k, v, _, _ in links]
        self.assertIn(("private", "AbCd1234"), got)
        self.assertIn(("private", "ZzZz999"), got)
        self.assertIn(("private", "TgHash77"), got)
        self.assertIn(("public", "Deals_Hub"), got)
        self.assertIn(("public", "NewsFlash"), got)
        self.assertIn(("public", "solo_channel"), got)
        self.assertEqual(len([g for g in got if g[1].lower() == "deals_hub"]), 1)
        self.assertEqual(repeats, 3)  # AbCd1234, deals_hub x2
        bad = {"addlist", "c", "abcdef", "ab", "gmail"}
        self.assertFalse(any(v.lower() in bad for _, v in got))

    def test_600_links(self):
        text = "\n".join(f"https://t.me/+Hash{i:05d}xyz" if i % 2 else f"https://t.me/chan_{i:04d}"
                         for i in range(600))
        links, repeats = extract_links(text)
        self.assertEqual((len(links), repeats), (600, 0))

    def test_collect_text_entities_and_buttons(self):
        class Ent:  # hidden hyperlink
            url = "https://t.me/+HiddenHash1"

        class Btn:
            url = "https://t.me/button_chan"

        class Msg:
            raw_text = "Join karo"
            buttons = [[Btn()]]

            def get_entities_text(self):
                return [(Ent(), "Join karo")]

        links, _ = extract_links(collect_text(Msg()))
        self.assertEqual({v for _, v, _, _ in links}, {"HiddenHash1", "button_chan"})


class DbTests(unittest.TestCase):
    def test_dedupe_and_restart_resume(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "j.db")
            db = Database(path)
            links, _ = extract_links("t.me/aaaa1 t.me/bbbb2 t.me/+cccc3")
            self.assertEqual(db.add(links)[0], 3)
            row = db.next_pending()
            db.start(row["id"])  # 'processing' me crash
            self.assertEqual(db.counts().get("processing"), 1)
            db2 = Database(path)  # restart
            self.assertEqual(db2.counts(), {"pending": 3})
            new, dups = db2.add(links)
            self.assertEqual((new, len(dups)), (0, 3))  # dobara process nahi


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_statuses_flood_limit_and_report(self):
        script = {
            "expired1": [InviteHashExpiredError()],
            "invalid1": [InviteHashInvalidError()],
            "ghost": [UsernameNotOccupiedError()],
            "req1": [InviteRequestSentError()],
            "already1": [UserAlreadyParticipantError()],
            "flooded": [FloodWaitError(1), joined("flooded")],
            "boom": [RuntimeError("kuch toota")],
            "limited": [ChannelsTooMuchError(), joined("limited")],
        }
        ops = FakeOps(script, counts=[500, 500, 470])
        h = Harness(ops)
        text = "\n".join(f"t.me/{n}" for n in
                         ["goodchan", "expired1", "invalid1", "ghost", "req1", "already1",
                          "flooded", "boom", "limited", "lastgood"])
        reply = h.add(text)
        self.assertIn("Naye queue me: 10", reply)
        await h.run_until_report()

        st = {r["url"].split("/")[-1]: r["status"] for r in h.db.conn.execute("SELECT * FROM links")}
        self.assertEqual(st["goodchan"], "joined")
        self.assertEqual(st["expired1"], "expired")
        self.assertEqual(st["invalid1"], "invalid")
        self.assertEqual(st["ghost"], "not_found")
        self.assertEqual(st["req1"], "request_sent")
        self.assertEqual(st["already1"], "already_joined")
        self.assertEqual(st["flooded"], "joined")      # FloodWait ke baad resume
        self.assertEqual(st["boom"], "failed")
        self.assertEqual(st["limited"], "joined")      # limit full -> cleanup -> resume
        self.assertEqual(st["lastgood"], "joined")     # invalid links se process nahi ruka
        self.assertEqual(ops.calls.count("flooded"), 2)
        self.assertEqual(ops.calls.count("limited"), 2)
        self.assertTrue(any("Channel limit full" in n for n in h.notes))

        text, files = h.reports[0]
        self.assertIn("Total Processed: 10", text)
        self.assertIn("Successfully Joined: 4", text)
        self.assertIn("Already Joined: 1", text)
        self.assertIn("Join Requests Sent: 1", text)
        self.assertIn("Invalid Links: 3", text)
        self.assertIn("Failed Links: 1", text)
        self.assertIn("https://t.me/expired1", text)   # chhoti list inline
        self.assertEqual(files, [])
        self.assertFalse(h.db.has_unreported())        # report ke baad batch band

        # same links dobara bhejo -> process nahi hote, status batata hai
        again = h.add("t.me/goodchan t.me/expired1")
        self.assertIn("already join ho chuka", again)
        self.assertIn("expired/private", again)
        self.assertEqual(h.db.pending_count(), 0)

    async def test_big_report_goes_to_txt(self):
        ops = FakeOps({f"dead{i:04d}": [InviteHashExpiredError()] for i in range(200)})
        h = Harness(ops)
        h.add("\n".join(f"t.me/dead{i:04d}" for i in range(200)) + "\nt.me/+Fine1234567")
        await h.run_until_report(timeout=20)
        text, files = h.reports[0]
        self.assertIn("TXT file", text)
        self.assertEqual(files[0][0], "invalid_links.txt")
        self.assertEqual(len(files[0][1].decode().splitlines()), 200)

    async def test_restart_resumes_pending_and_force_resume(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "j.db")
            h1 = Harness(FakeOps(), Database(path))
            h1.add("t.me/onechan t.me/twochan t.me/threechan")
            row = h1.db.next_pending()
            h1.db.start(row["id"])  # server beech me gir gaya
            ops2 = FakeOps({"twochan": [ChannelsTooMuchError(), joined("twochan")]}, counts=[500])
            h2 = Harness(ops2, Database(path))  # restart
            task = asyncio.create_task(h2.worker.run())
            for _ in range(100):  # limit par ruk jaayega
                if h2.worker.limit_hit:
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(h2.worker.limit_hit)
            await run_command("/resume", h2.db, h2.worker)  # manual resume
            for _ in range(200):
                if h2.reports:
                    break
                await asyncio.sleep(0.02)
            task.cancel()
            self.assertEqual(h2.db.counts(), {"joined": 3})
            self.assertEqual(len(h2.reports), 1)

    async def test_stats_text_and_pause(self):
        h = Harness(FakeOps())
        self.assertIn("queue khali", stats_text(h.db, h.worker))
        h.add("t.me/aaaaa t.me/bbbbb")
        s = stats_text(h.db, h.worker)
        for key in ["Total Links: 2", "Successfully Joined", "Already Joined", "Failed Links",
                    "Invalid Links", "Join Requests Sent", "Pending Links: 2",
                    "Currently Processing", "FloodWait Status", "Progress", "0.0%"]:
            self.assertIn(key, s)
        await run_command("/pause", h.db, h.worker)
        self.assertIn("Paused", stats_text(h.db, h.worker))

    async def test_flood_status_in_stats(self):
        h = Harness(FakeOps({"slowone": [FloodWaitError(2), joined("slowone")]}))
        h.worker.flood_padding = 0
        h.add("t.me/slowone")
        task = asyncio.create_task(h.worker.run())
        seen = False
        for _ in range(100):
            if "Active" in stats_text(h.db, h.worker):
                seen = True
                break
            await asyncio.sleep(0.02)
        task.cancel()
        self.assertTrue(seen)

    async def test_fatal_error_stops_without_losing_link(self):
        h = Harness(FakeOps({"zzzzz": [UserDeactivatedBanError()]}))
        h.add("t.me/zzzzz")
        task = asyncio.create_task(h.worker.run())
        for _ in range(100):
            if h.worker.fatal:
                break
            await asyncio.sleep(0.02)
        task.cancel()
        self.assertEqual(h.worker.fatal, "UserDeactivatedBanError")
        self.assertEqual(h.db.counts(), {"pending": 1})


if __name__ == "__main__":
    unittest.main()
