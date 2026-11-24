import time

INVALID_STATUSES = ("invalid", "expired", "not_found")

STATUS_LABEL = {
    "joined": "Successfully Joined",
    "already_joined": "Already Joined",
    "request_sent": "Join Request Sent",
    "invalid": "Invalid Invite Link",
    "expired": "Private Channel / Invite Expired",
    "not_found": "Channel Not Found",
    "failed": "Other Error",
}

DUP_LABEL = {
    "pending": "⏳ already queue / in process me hai",
    "processing": "⏳ already queue / in process me hai",
    "joined": "✅ already join ho chuka hai",
    "already_joined": "♻️ already joined tha",
    "request_sent": "📨 join request pehle hi bhej chuka hu",
    "invalid": "🚫 pehle invalid nikla tha",
    "expired": "🚫 pehle expired/private nikla tha",
    "not_found": "🚫 pehle channel not found nikla tha",
    "failed": "⚠️ pehle fail hua tha (/retry se dobara)",
}


def fmt_secs(n):
    n = max(0, int(n))
    h, rem = divmod(n, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _bar(pct):
    filled = int(pct // 10)
    return "█" * filled + "░" * (10 - filled)


def stats_text(db, worker, now=None):
    now = now or time.time()
    batch = db.has_unreported()
    c = db.counts(batch_only=batch)
    total = sum(c.values())
    if not total:
        return "📊 Abhi queue khali hai. Channel links bhejo."

    pending, processing = c.get("pending", 0), c.get("processing", 0)
    done = total - pending - processing
    pct = done * 100 / total
    invalid = sum(c.get(s, 0) for s in INVALID_STATUSES)

    flood_until = float(db.meta_get("flood_until", "0") or 0)
    if flood_until > now:
        flood = f"⏳ Active — {fmt_secs(flood_until - now)} baaki"
    else:
        flood = "✅ None"

    current = db.processing_row()
    current_txt = current["url"] if current else "—"
    scope = "Current batch" if batch else "All links"

    return "\n".join([
        f"📊 Live Stats ({scope})",
        "",
        f"Total Links: {total}",
        f"✅ Successfully Joined: {c.get('joined', 0)}",
        f"♻️ Already Joined: {c.get('already_joined', 0)}",
        f"⚠️ Failed Links: {c.get('failed', 0)}",
        f"🚫 Invalid Links: {invalid}",
        f"📨 Join Requests Sent: {c.get('request_sent', 0)}",
        f"⏳ Pending Links: {pending}",
        f"🔄 Currently Processing: {current_txt}",
        f"🌊 FloodWait Status: {flood}",
        f"📈 Progress: {_bar(pct)} {pct:.1f}% ({done}/{total})",
        "",
        f"{worker.status_label()} · gap {worker.delay:.1f}s",
    ])


def _line(row):
    txt = f"{row['url']} — {STATUS_LABEL.get(row['status'], row['status'])}"
    if row["detail"]:
        txt += f" ({row['detail']})"
    return txt


def build_report(db, batch_only=True, title="✅ Final Report"):
    """returns (text, files) ; files = [(filename, bytes)]"""
    rows = db.rows_for_report(batch_only)
    if not rows:
        return "Report ke liye abhi koi processed link nahi hai.", []

    n = {}
    for r in rows:
        n[r["status"]] = n.get(r["status"], 0) + 1
    invalid_rows = [r for r in rows if r["status"] in INVALID_STATUSES]
    failed_rows = [r for r in rows if r["status"] == "failed"]

    head = [
        title,
        "",
        f"Total Processed: {len(rows)}",
        f"✅ Successfully Joined: {n.get('joined', 0)}",
        f"♻️ Already Joined: {n.get('already_joined', 0)}",
        f"📨 Join Requests Sent: {n.get('request_sent', 0)}",
        f"🚫 Invalid Links: {len(invalid_rows)} "
        f"(invalid {n.get('invalid', 0)} · expired/private {n.get('expired', 0)} "
        f"· not found {n.get('not_found', 0)})",
        f"⚠️ Failed Links: {len(failed_rows)}",
    ]

    invalid_lines = [_line(r) for r in invalid_rows]
    failed_lines = [_line(r) for r in failed_rows]
    inline = []
    if invalid_lines:
        inline += ["", "🚫 Invalid Links:"] + invalid_lines
    if failed_lines:
        inline += ["", "⚠️ Failed Links:"] + failed_lines

    text = "\n".join(head + inline)
    files = []
    if len(text) > 3500:  # lambi list -> TXT file
        text = "\n".join(head + ["", "📎 Invalid aur Failed links ki poori list TXT file me hai."])
        if invalid_lines:
            files.append(("invalid_links.txt", "\n".join(invalid_lines).encode("utf-8")))
        if failed_lines:
            files.append(("failed_links.txt", "\n".join(failed_lines).encode("utf-8")))
    return text, files
