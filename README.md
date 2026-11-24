# Channel Joiner (Control Bot + Userbot)

Bot me links bhejo → aapka account ek-ek karke sab join karta hai, jab tak queue khatam na ho.
Status, pause/resume, failed list sab bot chat me.

## Setup (Railway)
1. my.telegram.org se `API_ID`, `API_HASH`. @BotFather se bot banao → `BOT_TOKEN`.
2. Railway Variables: `API_ID`, `API_HASH`, `BOT_TOKEN`. Volume `/data` mount karo + `DB_PATH=/data/joiner.db`.
3. Deploy. Apne bot ko Telegram me `/start` bhejo (pehla user = owner).
4. Bot me `/login` → phone number → OTP (**dashes ke saath: 1-2-3-4-5**) → 2FA password (agar ho).
   Session string banana nahi padta. (Purana tareeka chahiye to `SESSION_STRING` variable bhi chalta hai.)
5. Links bhejo (text ya .txt file).

## Features
- Ek-ek karke join, queue khatam hone tak; restart ke baad resume (SQLite)
- Bot me live status: `/status` (buttons), `/live` (auto-update)
- `/pause` `/resume` `/failed` `/retry` `/export` `/delay` `/clear` `/login` `/logout`
- Failed link ka turant notification (reason ke saath), end me summary, 25+ failed ho to file
- FloodWait auto-handle (exact wait + delay adaptive), account limit pe auto-pause + alert
- Public/private/join-request links, duplicates skip, already-joined detect
- Sirf owner control kar sakta hai

## Zaroori
- Limit: normal account ~500 channels/groups, Premium ~1000.
- Speed Telegram limit se tay hoti hai; delay bahut kam karoge to FloodWait/ban risk.
- Volume nahi lagaya to redeploy ke baad `/login` dobara + queue reset hogi.

## Test
`python tests/test_logic.py` aur `python tests/test_app.py` (fake Telegram client).
