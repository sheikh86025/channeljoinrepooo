import io

from links import collect_text, extract_links
from reports import DUP_LABEL, build_report, stats_text

HELP = (
    "🚀 Fast Channel Joiner\n\n"
    "Channel links bhejo — message me, forwarded post me, ya .txt file me. "
    "Telegram ek message me ~4000 characters hi allow karta hai, to 500-600 links "
    "kai messages me ya .txt file me bhejo. Main sab queue me daal kar ek-ek karke join karunga. "
    "Links dobara bhejne ki zarurat nahi.\n\n"
    "/stats - live progress\n"
    "/pause - rok do\n"
    "/resume - dobara chalu (cleanup ke baad bhi)\n"
    "/retry - failed links dobara try\n"
    "/report - abhi tak ki report"
)


def handle_links_text(db, worker, text):
    """Links nikal kar queue me daalta hai. Reply text return karta hai (links na mile to None)."""
    links, repeats = extract_links(text)
    if not links:
        return None
    new, dups = db.add(links)
    if new:
        worker.notify_new_links()

    lines = [
        f"📥 Links mile: {len(links) + repeats}",
        f"➕ Naye queue me: {new}",
        f"🔁 Already / repeat: {len(dups) + repeats}",
        f"⏳ Total pending: {db.pending_count()}",
    ]
    if dups:
        lines.append("")
        for url, status in dups[:15]:
            lines.append(f"{url} → {DUP_LABEL.get(status, status)}")
        if len(dups) > 15:
            lines.append(f"... aur {len(dups) - 15} links already DB me hain")
    if repeats:
        lines.append(f"(isi message me {repeats} link repeat the)")
    return "\n".join(lines)


async def run_command(cmd, db, worker):
    """returns (reply_text, files)"""
    if cmd == "/start":
        return HELP, []
    if cmd == "/stats":
        return stats_text(db, worker), []
    if cmd == "/pause":
        worker.paused = True
        return "⏸ Paused. /resume se dobara chalu karo.", []
    if cmd == "/resume":
        worker.paused = False
        worker.force_resume = True
        return "▶️ Resume.", []
    if cmd == "/retry":
        n = db.retry_failed()
        if n:
            worker.notify_new_links()
        return f"🔄 {n} failed links dobara queue me daale.", []
    if cmd == "/report":
        return build_report(db, batch_only=db.has_unreported(), title="📋 Report")
    return "Unknown command. /start dekho.", []


def _make_file(name, data):
    buf = io.BytesIO(data)
    buf.name = name
    return buf


def register(bot, cfg, db, worker):
    from telethon import events  # lazy: tests ko telethon ki zarurat nahi

    async def reply(ev, text, files=()):
        await ev.reply(text[:4000], parse_mode=None, link_preview=False)
        for name, data in files:
            await bot.send_file(cfg.owner_id, _make_file(name, data),
                                caption=name, force_document=True)

    @bot.on(events.NewMessage(from_users=cfg.owner_id, incoming=True))
    async def on_message(ev):
        raw = ev.raw_text or ""
        if raw.startswith("/"):
            cmd = raw.split()[0].split("@")[0].lower()
            text, files = await run_command(cmd, db, worker)
            await reply(ev, text, files)
            return

        text = collect_text(ev.message)
        f = ev.message.file
        if f and ((f.name or "").lower().endswith((".txt", ".csv"))
                  or (f.mime_type or "").startswith("text/")):
            data = await ev.message.download_media(file=bytes)
            text += "\n" + data.decode("utf-8", "ignore")

        answer = handle_links_text(db, worker, text)
        await reply(ev, answer or "Koi Telegram channel link nahi mila. /start dekho.")
