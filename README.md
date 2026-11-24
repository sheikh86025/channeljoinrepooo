# 🚀 Fast Channel Joiner (Telegram UserBot)

Ek userbot jo aapke diye hue 500–600 channel links ko **ek-ek karke automatically join** karta hai.
Control ek normal Telegram bot se hota hai (links bhejo, `/stats` dekho, report pao).

## Features

- **Bulk links:** message, forwarded post (hidden hyperlinks aur buttons ke links bhi), ya `.txt` file — sab se links apne aap nikalta hai
- **Links dobara bhejne ki zarurat nahi:** sab SQLite me save hote hain
- **Maximum safe speed:** ek join khatam hote hi agla; gap chhota (default 2s → 1s tak) aur FloodWait aane par khud adjust
- **FloodWait auto-recovery:** Telegram jitne second bole utna wait, phir khud resume. Restart ho jaye tab bhi bacha hua wait yaad rehta hai
- **Har link ka alag result:** Joined / Already Joined / Invalid / Expired-Private / Not Found / Join Request Sent / Other Error
- **Invalid link se process nahi rukta**
- **Duplicate links:** dobara bhejne par bot batata hai "already join ho chuka" ya "queue me hai"; process nahi hota
- **`/stats`:** live progress, FloodWait status
- **Final report:** queue khatam hote hi apne aap; lambi list ho to TXT file
- **Channel limit (500 / Premium 1000):** limit full hote hi bot "cleanup karo" bolta hai, aap leave karo, bot khud resume karta hai

## Files (sab ek hi folder me, koi subfolder nahi)

| File | Kaam |
|---|---|
| `main.py` | entry point |
| `config.py` | env settings |
| `database.py` | SQLite (progress, resume) |
| `links.py` | message se links nikalna |
| `worker.py` | join loop, FloodWait, limit, final report |
| `telegram_ops.py` | Telethon se asli join |
| `handlers.py` | bot commands / links intake |
| `reports.py` | `/stats` aur report text |
| `gen_session.py` | SESSION_STRING banane ke liye (ek baar) |
| `test_joiner.py` | tests |
| `requirements.txt`, `railway.json` | deploy files |

## GitHub par daalna

1. github.com → **New repository** (Private rakho) → naam do → Create
2. **"uploading an existing file"** link par tap karo
3. Saari files ek saath select karke upload karo (file picker me multi-select hota hai) → **Commit changes**
4. Dhyan: `SESSION_STRING` ya `BOT_TOKEN` kisi file me mat likhna — ye sirf Railway Variables me jayenge

## Setup

1. **API ID / HASH:** https://my.telegram.org → API development tools
2. **Bot token:** @BotFather se naya bot banao (ye sirf control panel hai)
3. **OWNER_ID:** apna Telegram numeric ID (@userinfobot se milta hai). Sirf yahi ID bot use kar sakti hai
4. **SESSION_STRING:** laptop/PC par ek baar

   ```bash
   pip install telethon
   python gen_session.py
   ```
   Phone number aur OTP daalo. Jo lambi string aaye wo `SESSION_STRING` hai.
   ⚠️ Ye string account ka poora access hai — kisi ko mat dena.
   **Spare account use karna better hai** (mass joining me ban/limit ka risk rehta hai).
5. Bot ko Telegram me khol kar ek baar **/start** bhejo (warna wo aapko message nahi bhej payega)

## Bina SESSION_STRING ke login (PHONE_NUMBER se)

`SESSION_STRING` ki jagah Railway Variables me bas `PHONE_NUMBER` (jaise `+919876543210`) daalo.
1. Deploy karo → control bot me message aayega "Login chahiye".
2. Account me jo code aaye wo bot me bhejo, **digits ke beech space ke saath**: `/otp 1 2 3 4 5`
3. 2-step password ho to: `/password aapka_password` (bot message delete kar deta hai)
4. Code nahi aaya to `/resend`
5. Login ke baad bot nayi `SESSION_STRING` bhejta hai — use Variables me daal do taaki redeploy par dobara OTP na lage.

## Environment variables

| Name | Zaruri | Default | Matlab |
|---|---|---|---|
| `API_ID`, `API_HASH` | ✅ | – | my.telegram.org se |
| `BOT_TOKEN` | ✅ | – | BotFather ka token |
| `OWNER_ID` | ✅ | – | aapka Telegram ID |
| `SESSION_STRING` | ❌ (agar PHONE_NUMBER diya) | – | userbot session |
| `PHONE_NUMBER` | ❌ (agar SESSION_STRING diya) | – | +91... number, bot OTP se login karwayega |
| `DB_PATH` | | `joiner.db` | SQLite file ka path (Railway par `/data/joiner.db`) |
| `START_DELAY` | | `2` | shuruaati gap (sec) |
| `MIN_DELAY` | | `1` | gap isse kam nahi hoga |
| `MAX_DELAY` | | `30` | FloodWait ke baad gap isse zyada nahi |
| `MIN_FREE` | | `20` | limit full ke baad itne channels leave hone par auto resume |
| `REPORT_DEBOUNCE` | | `20` | queue khali hone ke itne sec baad final report |

## Run

**Railway (recommended):**
1. New Project → Deploy from GitHub repo → apna repo chuno
2. **Variables** me upar wale env daalo
3. **Volume** banao, mount path `/data`, aur `DB_PATH=/data/joiner.db` set karo — warna redeploy par progress ud jayegi
4. Start command `python main.py` (`railway.json` me pehle se hai)
5. Logs me error na ho aur bot aapko "🟢 Bot chalu" message bheje, to sahi chal raha hai

**Local:**
```bash
pip install -r requirements.txt
```
Ek `.env` file banao jisme `API_ID=...`, `API_HASH=...`, `BOT_TOKEN=...`, `OWNER_ID=...`, `SESSION_STRING=...` likho, phir:
```bash
python main.py
```

## Use kaise karein

1. Bot ko links bhejo. Telegram ek message me ~4000 characters hi deta hai, isliye 500–600 links
   **kai messages me ya ek `.txt` file me** bhejo (har line me ek link). Forward kiye hue posts bhi chalte hain.
2. Bot turant batata hai: kitne naye queue me gaye, kitne repeat the.
3. Joining apne aap shuru. `/stats` se progress dekho.
4. Sab khatam hone par final report apne aap aayegi.

Links jo pehchane jaate hain: `https://t.me/name`, `t.me/+hash`, `t.me/joinchat/hash`, `tg://join?invite=hash`,
aur akeli line me `@username`.

### Commands

| Command | Kaam |
|---|---|
| `/stats` | Total, Joined, Already Joined, Failed, Invalid, Join Requests, Pending, Currently Processing, FloodWait status, Progress % |
| `/pause` | joining rok do |
| `/resume` | dobara chalu (limit full ke baad cleanup karke bhi) |
| `/retry` | Other-Error wale links dobara try |
| `/report` | abhi tak ki report |

### Status ka matlab

| Status | Matlab |
|---|---|
| Successfully Joined | join ho gaya |
| Already Joined | pehle se member tha |
| Join Request Sent | channel me admin approval chahiye, request bhej di |
| Invalid Invite Link | link galat hai |
| Private Channel / Invite Expired | invite expire/revoke ya channel private/banned |
| Channel Not Found | username exist nahi karta / channel nahi hai |
| Other Error | koi aur dikkat (reason report me likha hota hai) |

**Invalid Links** report = Invalid + Expired/Private + Not Found. **Failed** = Other Error.

## Dhyan rakhne wali baatein

- **Speed:** Telegram har account par join ki limit lagata hai. Isliye 600 channels kuch minute me nahi honge —
  bot jitna tez safe hai utna chalta hai, FloodWait aaye to khud ruk kar aage badhta hai. Gap zero karne se
  FloodWait aur lamba hota hai aur account restrict ho sakta hai.
- **Channel limit:** free account me 500, Premium me 1000 channels/groups. 600 links ho to limit aayegi:
  bot batayega, aap kuch channels leave karo (jaise inactive wale), bot khud resume karega.
- Join-request wale channels me request jati hai; approve hone par hi aap member banoge.
- Sirf `OWNER_ID` bot ko control kar sakta hai.

## Tests

```bash
python -m unittest test_joiner -v
```
Tests Telegram ke bina chalte hain (fake Telegram se): link parsing, SQLite resume, sabhi statuses,
FloodWait recovery, channel limit pause/resume, final report aur TXT file.
