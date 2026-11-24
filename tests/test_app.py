import asyncio, os, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
try:
    import telethon.errors
    USING = "REAL telethon"
except ImportError:
    sys.path.insert(0, os.path.join(HERE, "stub_telethon")); USING = "STUB telethon (offline)"
from telethon import errors as E
from config import Config
from db import DB
from app import App


class Msg:
    def __init__(self): self.edits = []
    async def edit(self, t): self.edits.append(t)

class FakeBot:
    def __init__(self): self.sent, self.files = [], []
    async def send_message(self, chat, text, **kw):
        self.sent.append((chat, text)); return Msg()
    async def send_file(self, chat, f, caption=""):
        self.files.append((chat, f.name, f.read().decode(), caption))
    def texts(self): return [t for _, t in self.sent]

class Upd:
    def __init__(self, t): self.chats = [types.SimpleNamespace(title=t)]

class FU:
    def __init__(self, login=False): self.login, self.pw_ok = login, False; self.session = types.SimpleNamespace(save=lambda: "1FAKESESSION")
    async def connect(self): pass
    async def disconnect(self): pass
    async def is_user_authorized(self): return True
    async def get_me(self): return types.SimpleNamespace(first_name="Test", username="tester")
    async def send_code_request(self, phone): return types.SimpleNamespace(phone_code_hash="H")
    async def sign_in(self, phone=None, code=None, password=None, phone_code_hash=None):
        if code is not None:
            if code != "12345": raise E.PhoneCodeInvalidError()
            raise E.SessionPasswordNeededError()
        if password != "secret": raise E.PasswordHashInvalidError()
    async def log_out(self): self.logged_out = True
    async def __call__(self, req): return Upd(req.key)

def factory(s):
    if s.startswith("BAD"): raise ValueError("Not a valid string")
    return FU(login=(s == ""))

class Ev:
    def __init__(self, uid, text): self.sender_id, self.raw_text = uid, text; self.message = types.SimpleNamespace(file=None); self.deleted = False
    async def delete(self): self.deleted = True

def mk(owner=42, session=""):
    cfg = Config(api_id=1, api_hash="x", bot_token="1:x", owner_id=owner, session_string=session,
                 delay_min=0, delay_max=0, idle_wait=0.02)
    db = DB(os.path.join(tempfile.mkdtemp(), "a.db")); bot = FakeBot()
    return App(cfg, db, bot, factory), db, bot

async def main():
    print("Using:", USING)
    # 1) bad SESSION_STRING crash nahi karta, saaf message deta hai
    app, db, bot = mk(session="BADSTRING")
    await app.boot()
    assert "format galat" in bot.texts()[-1] and app.joiner is None
    print("bad session -> clear message, no crash OK")

    # 2) non-owner ignore, links bina login ke queue me
    await app.on_message(Ev(999, "/status")); assert len(bot.sent) == 1
    await app.on_message(Ev(42, "https://t.me/chanone https://t.me/+AbCdEfGhIjKlMn @chantwo"))
    assert db.pending_count() == 3 and "login nahi hai" in bot.texts()[-1]
    await app.on_message(Ev(42, "/status")); assert "Pending: 3" in bot.texts()[-1]
    print("non-owner ignored, queue w/o login OK")

    # 3) /login flow: phone -> galat code -> sahi code -> 2FA galat -> 2FA sahi
    await app.on_message(Ev(42, "/login")); assert app.login["step"] == "phone"
    await app.on_message(Ev(42, "98765")); assert app.login["step"] == "phone" and "+" in bot.texts()[-1]
    await app.on_message(Ev(42, "+91 98765 43210")); assert app.login["step"] == "code" and "DASHES" in bot.texts()[-1]
    e = Ev(42, "9-9-9-9-9"); await app.on_message(e)
    assert app.login["step"] == "code" and "galat" in bot.texts()[-1] and e.deleted
    await app.on_message(Ev(42, "1-2-3-4-5")); assert app.login["step"] == "password"
    await app.on_message(Ev(42, "wrong")); assert app.login["step"] == "password" and "Password galat" in bot.texts()[-1]
    e = Ev(42, "secret"); await app.on_message(e)
    assert app.login is None and e.deleted and db.get("session") == "1FAKESESSION"
    assert app.joiner is not None and "Login ho gaya: Test @tester" in " ".join(bot.texts())
    print("login flow (phone/code/2FA, retries, msg delete) OK")

    # 4) pending queue login ke baad apne aap join hui
    await asyncio.wait_for(app.joiner.idle.wait(), 3)
    c = db.counts(); assert c["joined"] == 3 and c["pending"] == 0, c
    await app.on_message(Ev(42, "/status")); st = bot.texts()[-1]
    assert "Joined: 3" in st and "Last 24h joined: 3" in st, st
    print("queued links auto-joined after login OK")
    print("--- status ---"); print(st)

    # 5) pause/resume/export/failed/delay/logout
    await app.on_message(Ev(42, "/pause")); assert app.joiner.paused
    await app.on_message(Ev(42, "/resume")); assert not app.joiner.paused
    await app.on_message(Ev(42, "/export")); assert any(f[1] == "joined.txt" and "chanone" in f[2] for f in bot.files)
    await app.on_message(Ev(42, "/failed")); assert "Koi failed" in bot.texts()[-1]
    await app.on_message(Ev(42, "/delay 2 5")); assert (app.cfg.delay_min, app.cfg.delay_max) == (2, 5)
    await app.on_message(Ev(42, "/logout")); assert app.joiner is None and db.get("session") is None
    print("pause/resume/export/failed/delay/logout OK")

    # 6) owner claim: pehla /start owner banata hai
    app2, db2, bot2 = mk(owner=0)
    await app2.on_message(Ev(7, "hello")); assert not bot2.sent
    await app2.on_message(Ev(7, "/start")); assert db2.get("owner") == "7" and bot2.sent[0][0] == 7
    await app2.on_message(Ev(8, "/status")); n = len(bot2.sent); assert n == len(bot2.sent)
    print("owner claim OK")
    # 7) valid env session boot
    app3, db3, bot3 = mk(session="1VALID"); await app3.boot()
    assert app3.joiner and "Userbot online" in bot3.texts()[-1]; await app3.stop_userbot()
    print("\nALL APP TESTS PASSED")
asyncio.run(main())
