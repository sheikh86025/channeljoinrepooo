# Channel Joiner Userbot

Aap Saved Messages me links bhejo (text ya .txt file) → userbot ek-ek karke sab join karta hai,
tab tak jab tak queue khatam na ho. Jo join na ho uska notification Saved Messages me aata hai.

## Setup (Railway)
1. https://my.telegram.org se `API_ID` aur `API_HASH` lo.
2. Apne PC pe: `pip install telethon` → `python gen_session.py` → phone/OTP daalo → `SESSION_STRING` copy karo.
   (Ye string account ka full access hai, kisi ko mat dena.)
3. GitHub pe push karo → Railway me deploy.
4. Railway Variables: `API_ID`, `API_HASH`, `SESSION_STRING`.
5. (Recommended) Railway Volume banao, mount path `/data`, aur variable `DB_PATH=/data/joiner.db`
   taaki redeploy ke baad queue/history na jaye.

## Use
Saved Messages me links paste karo ya .txt file bhejo. Commands:
`/status` `/pause` `/resume` `/failed` `/retry` `/delay 3 6` `/clear` `/help`

## Notifications
- Start, har `PROGRESS_EVERY` joins pe progress, end me summary
- Har failed link turant (reason ke saath) — `NOTIFY_EACH_FAIL=0` se sirf end summary
- FloodWait, account limit, session problem pe alert

## Zaroori baatein
- **Limit:** ek account me normally ~500 channels/groups, Premium me ~1000. Limit aate hi bot pause
  hokar notify karta hai (pending links safe rehte hain). 800+ ke liye Premium ya 2nd account chahiye.
- **Speed:** default 3–6s per join. Telegram khud joins rate-limit karta hai; FloodWait aaye to bot
  exact utna ruk ke apne aap continue karta hai aur delay thoda badha deta hai. Delay bahut kam
  karoge to FloodWait/ban risk badhta hai.
- Join request wale channels me "request sent" count hota hai (admin approve kare tab join).

## Test
`python tests/test_logic.py` (logic test, fake Telegram client ke saath).
