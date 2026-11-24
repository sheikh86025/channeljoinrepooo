import asyncio, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
try:
    import telethon.errors  # real telethon ho to wahi use hoga
    USING = "REAL telethon"
except ImportError:
    sys.path.insert(0, os.path.join(HERE, "stub_telethon"))
    USING = "STUB telethon (offline)"

from telethon import errors as E
from config import Config
from db import DB
from joiner import Joiner
from linkparser import extract_links


class Chat: 
    def __init__(self, t): self.title = t
class Upd:
    def __init__(self, t): self.chats = [Chat(t)]


class FakeClient:
    """script[key] = list of outcomes; har call par ek nikalta hai. Exception ya title(str)."""
    def __init__(self, script): self.script, self.calls = script, []
    async def __call__(self, req):
        self.calls.append(req.key)
        seq = self.script.get(req.key)
        out = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(out, BaseException): raise out
        return Upd(out)


class FakeNotifier:
    def __init__(self): self.texts, self.files = [], []
    async def text(self, m): self.texts.append(m)
    async def file(self, n, d, c): self.files.append((n, d, c))


def mk(script, **kw):
    cfg = Config(delay_min=0, delay_max=0, idle_wait=0.02, progress_every=3, max_attempts=3, **kw)
    db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
    n = FakeNotifier()
    j = Joiner(FakeClient(script), db, cfg, n)
    sleeps = []
    async def fake_sleep(s): sleeps.append(s)
    j._sleep = fake_sleep
    return j, db, n, sleeps


async def run_until_idle(j, timeout=3):
    t = asyncio.create_task(j.run())
    try:
        await asyncio.wait_for(j.idle.wait(), timeout)
    finally:
        j.stop(); await t


def test_parser():
    txt = """https://t.me/+AbCdEfGhIjKlMn t.me/joinchat/XyZ1234567890 https://t.me/somechannel
    @another_chan tg://join?invite=Hash1234567890 t.me/somechannel/55 t.me/c/123/456 t.me/addstickers/foo
    mail me a@gmail.com https://t.me/+AbCdEfGhIjKlMn t.me/joinchat"""
    got = extract_links(txt)
    assert got == [("invite", "AbCdEfGhIjKlMn"), ("invite", "XyZ1234567890"), ("public", "somechannel"),
                   ("public", "another_chan"), ("invite", "Hash1234567890")], got
    print("parser OK:", len(got), "links")


async def test_all_outcomes():
    script = {
        "ok1": ["Chan One"], "ok2": ["Chan Two"],
        "already": [E.UserAlreadyParticipantError()],
        "req": [E.InviteRequestSentError()],
        "expired": [E.InviteHashExpiredError()],
        "badname": [E.UsernameNotOccupiedError()],
        "isuser": [ValueError("No user has x")],
        "flood": [E.FloodWaitError(7), "After Flood"],
        "flaky": [E.RpcCallFailError(), E.RpcCallFailError(), "Flaky OK"],
        "dead": [E.RpcCallFailError()],
    }
    j, db, n, sleeps = mk(script)
    items = [("public", k) for k in script]
    new, _, _ = db.add_links(items)
    assert new == len(script)
    await run_until_idle(j)
    c = db.counts()
    print("counts:", c)
    assert c["pending"] == 0
    assert c["joined"] == 4          # ok1 ok2 flood flaky
    assert c["already"] == 1 and c["request_sent"] == 1
    assert c["failed"] == 4          # expired badname isuser dead
    assert 9 in sleeps                # flood 7 + 2 buffer
    assert j.flood_hits == 1 and j.delay_factor > 1
    fails = [t for t in n.texts if t.startswith("❌")]
    assert len(fails) == 4, fails
    assert any("🏁" in t for t in n.texts)
    assert n.texts[0].startswith("▶️")
    assert any(t.startswith("📊") for t in n.texts)  # progress
    assert len([x for x in j.client.calls if x == "flood"]) == 2   # flood ke baad same link retry hua
    assert len([x for x in j.client.calls if x == "flaky"]) == 3
    assert len([x for x in j.client.calls if x == "dead"]) == 3    # max_attempts
    print("all outcomes OK")
    print("--- sample notifications ---"); print("\n\n".join(n.texts[-2:]))


async def test_limit_pause_resume():
    script = {"a": ["A"], "b": ["B"], "c": [E.ChannelsTooMuchError(), "C"], "d": ["D"]}
    j, db, n, _ = mk(script)
    db.add_links([("public", k) for k in script])
    t = asyncio.create_task(j.run())
    for _ in range(100):
        if j.paused: break
        await asyncio.sleep(0.02)
    assert j.paused, "limit pe pause nahi hua"
    assert db.counts()["pending"] == 2 and db.counts()["joined"] == 2
    assert any("limit" in x for x in n.texts)
    j.resume()
    await asyncio.wait_for(j.idle.wait(), 3)
    j.stop(); await t
    assert db.counts()["joined"] == 4 and db.counts()["pending"] == 0
    print("limit -> pause -> resume OK")


async def test_resume_after_restart_and_retry():
    script = {"x": [E.InviteHashExpiredError()], "y": ["Y"]}
    j, db, n, _ = mk(script)
    db.add_links([("public", "x"), ("public", "y")])
    await run_until_idle(j)
    assert db.counts()["failed"] == 1
    assert db.requeue_failed() == 1
    script["x"] = ["X now ok"]
    j.idle.clear(); j._stop = False
    await run_until_idle(j)
    assert db.counts()["joined"] == 2 and db.counts()["failed"] == 0
    # naya Joiner (restart simulate): pending bachi to continue
    db.add_links([("public", "z")])
    j2 = Joiner(FakeClient({"z": ["Z"]}), db, j.cfg, FakeNotifier())
    await run_until_idle(j2)
    assert db.counts()["joined"] == 3
    print("retry + restart-resume OK")


async def test_fatal_and_many_failed_file():
    j, db, n, _ = mk({"s": [E.SessionRevokedError()]})
    db.add_links([("public", "s")])
    t = asyncio.create_task(j.run()); await asyncio.sleep(0.2)
    assert j.fatal and db.counts()["pending"] == 1
    j.stop(); await t
    script = {f"bad{i:02d}x": [E.InviteHashExpiredError()] for i in range(30)}
    j, db, n, _ = mk(script, notify_each_fail=False)
    db.add_links([("public", k) for k in script])
    await run_until_idle(j)
    assert len(n.files) == 1 and not any(t.startswith("❌") for t in n.texts)
    print("fatal-session + 30 failed -> file OK")


async def main():
    print("Using:", USING)
    test_parser()
    await test_all_outcomes()
    await test_limit_pause_resume()
    await test_resume_after_restart_and_retry()
    await test_fatal_and_many_failed_file()
    print("\nALL TESTS PASSED")

asyncio.run(main())
