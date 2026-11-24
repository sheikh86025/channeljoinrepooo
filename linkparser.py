"""Text me se Telegram channel/group links nikalta hai."""
import re

RESERVED = {
    "joinchat", "addstickers", "addemoji", "share", "proxy", "socks", "addtheme",
    "setlanguage", "iv", "login", "confirmphone", "contact", "boost", "giftcode",
    "invoice", "msg", "c", "s", "m", "web", "k", "a",
}

_HOST = r"(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.me|telegram\.dog)"
PATTERN = re.compile(
    _HOST + r"/(?:\+|joinchat/)(?P<hash>[A-Za-z0-9_-]{10,})"
    r"|tg://join\?invite=(?P<hash2>[A-Za-z0-9_-]{10,})"
    r"|" + _HOST + r"/(?P<user>[A-Za-z][A-Za-z0-9_]{3,31})(?![A-Za-z0-9_])"
    r"|(?<![\w/.])@(?P<at>[A-Za-z][A-Za-z0-9_]{3,31})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def extract_links(text):
    """Returns [(kind, key)] dedup, order preserved. kind = 'invite' | 'public'."""
    out, seen = [], set()
    for m in PATTERN.finditer(text or ""):
        h = m.group("hash") or m.group("hash2")
        if h:
            item = ("invite", h)
        else:
            u = m.group("user") or m.group("at")
            if not u or u.lower() in RESERVED:
                continue
            item = ("public", u.lower())
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def to_url(kind, key):
    return f"https://t.me/+{key}" if kind == "invite" else f"https://t.me/{key}"
