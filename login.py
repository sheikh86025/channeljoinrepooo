"""Phone number se login — bot ke through (Railway par terminal nahi hota).

Flow:
  1. PHONE_NUMBER variable me number (+91...) daalo, deploy karo.
  2. Telegram app me us account par login code aayega.
  3. Control bot me bhejo:   /otp 1 2 3 4 5     (digits ke beech space dena — zaruri hai)
  4. 2-step password ho to:  /password apna_password
  5. Bot nayi SESSION_STRING bhejega — use Railway me SESSION_STRING me daal do.
"""
import asyncio
import logging
import re

from telethon import events
from telethon.errors import (FloodWaitError, PasswordHashInvalidError, PhoneCodeEmptyError,
                             PhoneCodeExpiredError, PhoneCodeInvalidError, PhoneNumberBannedError,
                             PhoneNumberInvalidError, SessionPasswordNeededError)

log = logging.getLogger("joiner.login")


async def login_with_phone(bot, user, cfg, notify):
    queue = asyncio.Queue()

    @bot.on(events.NewMessage(from_users=cfg.owner_id, incoming=True,
                              pattern=r"(?i)^/(otp|password|resend)\b"))
    async def on_login_cmd(ev):
        cmd, _, arg = (ev.raw_text or "").partition(" ")
        cmd = cmd.split("@")[0].lower()
        await queue.put((cmd, arg.strip()))
        if cmd == "/password":  # password chat me na rahe
            try:
                await ev.delete()
            except Exception:
                pass

    async def send_code():
        while True:
            try:
                return await user.send_code_request(cfg.phone)
            except FloodWaitError as e:
                await notify(f"⏳ Telegram ne code bhejne se {e.seconds}s roka hai. Bot khud dobara try karega.")
                await asyncio.sleep(e.seconds + 2)

    try:
        try:
            sent = await send_code()
        except (PhoneNumberInvalidError, PhoneNumberBannedError):
            raise SystemExit("PHONE_NUMBER galat/banned hai. Format: +919876543210")

        await notify(
            "📲 Login chahiye.\n\n"
            f"{cfg.phone} wale Telegram account me login code aaya hoga.\n"
            "Yahan bhejo (digits ke beech space ke saath, warna Telegram code block kar deta hai):\n\n"
            "/otp 1 2 3 4 5\n\n"
            "Code nahi aaya? /resend")

        while True:
            cmd, arg = await queue.get()
            if cmd == "/resend":
                sent = await send_code()
                await notify("🔁 Naya code bhej diya. /otp 1 2 3 4 5")
                continue
            if cmd != "/otp":
                continue
            code = re.sub(r"\D", "", arg)
            if not code:
                await notify("Code likho: /otp 1 2 3 4 5")
                continue
            try:
                await user.sign_in(cfg.phone, code, phone_code_hash=sent.phone_code_hash)
                break
            except SessionPasswordNeededError:
                await notify("🔐 2-step verification password chahiye:\n/password aapka_password")
                if await _ask_password(user, queue, notify):
                    break
            except (PhoneCodeInvalidError, PhoneCodeEmptyError):
                await notify("❌ Code galat hai. Dobara /otp bhejo ya /resend.")
            except PhoneCodeExpiredError:
                sent = await send_code()
                await notify("⌛ Code expire ho gaya. Naya bhej diya — /otp 1 2 3 4 5")
    finally:
        bot.remove_event_handler(on_login_cmd)

    session = user.session.save()
    try:
        with open(cfg.session_file, "w") as f:
            f.write(session)
    except OSError as e:
        log.warning("session file save fail: %s", e)

    await notify(
        "✅ Login ho gaya!\n\n"
        "Ye aapki SESSION_STRING hai. Isse Railway Variables me SESSION_STRING me daal do "
        "(taaki redeploy par dobara OTP na lage), phir PHONE_NUMBER hata sakte ho:\n\n"
        f"{session}\n\n"
        "⚠️ Ye account ka poora access hai — kisi ko mat dena. Daalne ke baad is message ko delete kar do.")
    return session


async def _ask_password(user, queue, notify):
    while True:
        cmd, arg = await queue.get()
        if cmd != "/password":
            continue
        try:
            await user.sign_in(password=arg)
            return True
        except PasswordHashInvalidError:
            await notify("❌ Password galat. Dobara: /password aapka_password")
