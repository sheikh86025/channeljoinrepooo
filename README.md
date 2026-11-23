# Telegram Bulk Channel Joiner

Ek baar mein 500-600 channel links bhejo, bot khud sabko ek-ek karke join karta hai.
FloodWait par auto-wait + auto-resume, SQLite mein progress save, `/stats` aur final report.

> Channel join karna sirf **user account** se hota hai (bot token se nahi), isliye ye Telethon userbot hai.
> Apna hi account use karo aur Telegram ke rules follow karo.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # API_ID / API_HASH daalo (https://my.telegram.org)
python main.py           # pehli baar phone + OTP maangega, phir session save ho jata hai
```

Headless server: ek baar local machine par login karke `SESSION_STRING` bana lo, ya server par pehli baar
terminal se login karo. Uske baad `python main.py` (ya systemd/pm2/screen) restart-safe hai.

## Use

1. Telegram mein apne **Saved Messages** kholo.
2. Links paste karo (t.me/+hash, t.me/joinchat/hash, t.me/username, @username). Ek message mein bahut links
   ho to bhi chalega; Telegram ka 4096-char limit hai (Premium: 4096 bhi), isliye 500-600 links **2-4 messages**
   mein ya ek **.txt file** mein bhejo. Bot sab messages combine kar leta hai, duplicates skip karta hai.
3. Bot automatically join shuru kar deta hai. Dobara links bhejne ki zaroorat nahi.

(Chaho to `OWNER_ID` set karke us user ke messages bhi accept kara sakte ho.)

## Commands

| Command | Kaam |
|---|---|
| `/stats` | Total, Joined, Already, Failed, Invalid, Requests, Pending, Currently Processing, FloodWait, Progress % |
| `/report` | Report dobara bhejo |
| `/pause`, `/resume` | Joining roko / chalu karo |
| `/retry` | Failed (not found / other error) links dobara queue karo |
| `/delay 1.5` | Base delay badlo |

## Kaise kaam karta hai

- **Speed:** ek link khatam hote hi agla start; sirf `JOIN_DELAY` (default 1s) ka chhota gap.
  FloodWait aane par delay automatic badhta hai (x1.5, max `MAX_DELAY`) aur 10 successful joins ke baad wapas
  kam hota hai. Isse Telegram ki limit ke andar rehkar maximum safe speed milti hai.
- **FloodWait:** `FloodWaitError.seconds + 1` sleep, phir *usi* link ko retry. Process kabhi stop nahi hota.
- **Result categories:** Joined, Already Joined, Invalid Invite Link, Private/Expired, Not Found,
  Join Request Sent, Other Errors. Invalid/expired link baaki process ko nahi rokta.
- **SQLite (`data/joiner.db`):** har link ka status save hota hai. Restart par `processing` wale link wapas
  pending ho jaate hain aur pending links se resume hota hai; joined links dobara process nahi hote.
- **Final report:** sab links khatam hone par (10s koi naya link nahi aaya to) summary + Failed/Invalid list.
  List badi ho (20 se zyada) to TXT file; saath mein har link ka CSV bhi aata hai.
- **Account limit:** Telegram account par joined channels ki limit hoti hai (~500; Premium zyada). Limit aane par
  bot pause hokar notify karta hai; kuch channels leave karke `/resume` karo.

## Important notes

- Bahut tez joining se account par limitation/ban lag sakta hai. Agar baar-baar badi FloodWait aaye to
  `JOIN_DELAY` badhao (jaise 3-5s).
- Public username links ke liye bot pehle check karta hai ki already member hai ya nahi.

## Structure

```
main.py
joinbot/  config.py  parser.py  db.py  joiner.py  reports.py  app.py
tests/    test_core.py
requirements.txt  .env.example  README.md
```

Tests: `python -m unittest discover -s tests -v`


## Hosted deployment: SESSION_STRING / EOFError

For a hosted server without an interactive terminal, set `SESSION_STRING` to a
**genuine authenticated Telethon StringSession**. Paste only the session value
(no surrounding quote characters); never share it publicly. The app connects
and checks authorization before starting. It will not call `input()` on a
non-interactive server.

If the StringSession is malformed, the app reports that directly. If it parses
but is not authorized, generate a fresh authenticated StringSession. If
`SESSION_STRING` is empty, an already-authorized `SESSION_NAME` session file
can be used, provided it is stored on persistent storage.
