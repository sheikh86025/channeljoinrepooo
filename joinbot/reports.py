"""Stats text and final report generation."""
import csv
import time
from pathlib import Path
from typing import List, Tuple

from . import db as D

INLINE_LIMIT = 20  # failed+invalid entries shown inline; more -> TXT file only


def link_url(row) -> str:
    if row["kind"] == "invite":
        return f"https://t.me/+{row['ref']}"
    return f"https://t.me/{row['ref']}"


def grouped(counts: dict) -> dict:
    return {
        "total": counts["total"],
        "joined": counts[D.JOINED],
        "already": counts[D.ALREADY],
        "invalid": sum(counts[s] for s in D.INVALID_GROUP),
        "failed": sum(counts[s] for s in D.FAILED_GROUP),
        "requests": counts[D.REQUEST_SENT],
        "pending": counts[D.PENDING],
        "processing": counts[D.PROCESSING],
    }


def progress_pct(g: dict) -> float:
    if not g["total"]:
        return 0.0
    done = g["total"] - g["pending"] - g["processing"]
    return done * 100.0 / g["total"]


def stats_text(counts: dict, current, flood_remaining: int, delay: float, paused: bool) -> str:
    g = grouped(counts)
    cur = link_url(current) if current else "None"
    flood = f"Active - {flood_remaining}s remaining" if flood_remaining > 0 else "None"
    lines = [
        "📊 Live Stats",
        "",
        f"Total Links: {g['total']}",
        f"✅ Successfully Joined: {g['joined']}",
        f"☑️ Already Joined: {g['already']}",
        f"❌ Failed Links: {g['failed']}",
        f"🚫 Invalid Links: {g['invalid']}",
        f"📨 Join Requests Sent: {g['requests']}",
        f"⏳ Pending Links: {g['pending']}",
        f"⚙️ Currently Processing: {cur}",
        f"🌊 FloodWait Status: {flood}",
        f"📈 Progress: {progress_pct(g):.1f}%",
        "",
        f"Delay between joins: {delay:.1f}s" + ("  |  ⏸ PAUSED" if paused else ""),
    ]
    return "\n".join(lines)


def _entry(row) -> str:
    label = D.STATUS_LABELS.get(row["status"], row["status"])
    d = f" - {row['detail']}" if row["detail"] else ""
    return f"{link_url(row)}  [{label}{d}]"


def final_summary(counts: dict) -> str:
    g = grouped(counts)
    processed = g["total"] - g["pending"] - g["processing"]
    return "\n".join(
        [
            "🏁 Final Report",
            "",
            f"Total Processed: {processed} / {g['total']}",
            f"✅ Successfully Joined: {g['joined']}",
            f"☑️ Already Joined: {g['already']}",
            f"🚫 Invalid Links: {g['invalid']}",
            f"❌ Failed Links: {g['failed']}",
            f"📨 Join Requests Sent: {g['requests']}",
            "",
            "Breakdown of problem links:",
            f"  Invalid Invite Link: {counts[D.INVALID]}",
            f"  Private Channel / Invite Expired: {counts[D.EXPIRED]}",
            f"  Channel Not Found: {counts[D.NOT_FOUND]}",
            f"  Other Errors: {counts[D.ERROR]}",
        ]
    )


def build_report(db: D.Database, reports_dir: str) -> Tuple[str, List[str]]:
    """Returns (message_text, [files_to_send])."""
    counts = db.counts()
    text = final_summary(counts)
    invalid = db.list_by_status(D.INVALID_GROUP)
    failed = db.list_by_status(D.FAILED_GROUP)
    files: List[str] = []
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    if invalid or failed:
        if len(invalid) + len(failed) <= INLINE_LIMIT:
            if invalid:
                text += "\n\n🚫 Invalid Links:\n" + "\n".join(_entry(r) for r in invalid)
            if failed:
                text += "\n\n❌ Failed Links:\n" + "\n".join(_entry(r) for r in failed)
        else:
            p = out / f"report_failed_invalid_{ts}.txt"
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"INVALID LINKS ({len(invalid)})\n" + "=" * 40 + "\n")
                f.writelines(_entry(r) + "\n" for r in invalid)
                f.write(f"\nFAILED LINKS ({len(failed)})\n" + "=" * 40 + "\n")
                f.writelines(_entry(r) + "\n" for r in failed)
            files.append(str(p))
            text += "\n\nComplete Failed + Invalid list attached as TXT."

    # Full per-link results, always available
    csv_path = out / f"report_all_results_{ts}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["link", "status", "detail", "attempts"])
        for r in db.all_rows():
            w.writerow([link_url(r), D.STATUS_LABELS.get(r["status"], r["status"]), r["detail"], r["attempts"]])
    files.append(str(csv_path))
    return text, files
