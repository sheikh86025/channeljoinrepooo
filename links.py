import re

# t.me/<kuch> jo channel nahi hote
RESERVED = {
    "addlist", "joinchat", "addstickers", "addemoji", "proxy", "socks", "share",
    "login", "boost", "setlanguage", "invoice", "giftcode", "contact", "iv",
}

LINK_RE = re.compile(
    r"tg://join\?invite=(?P<tg>[\w-]+)"
    r"|(?<![\w.])(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/"
    r"(?:(?:joinchat/|\+)(?P<priv>[\w-]+)|(?P<pub>[A-Za-z0-9_]{4,32}))",
    re.IGNORECASE,
)
AT_LINE_RE = re.compile(r"^@([A-Za-z0-9_]{4,32})$")


def make_key(kind, val):
    return f"private:{val}" if kind == "private" else f"public:{val.lower()}"


def make_url(kind, val):
    return f"https://t.me/+{val}" if kind == "private" else f"https://t.me/{val}"


def extract_links(text):
    """Text se saare channel links nikalta hai.

    returns (unique_links, repeats) -- link = (kind, val, url, key)
    """
    unique, seen, repeats = [], set(), 0

    def add(kind, val):
        nonlocal repeats
        key = make_key(kind, val)
        if key in seen:
            repeats += 1
            return
        seen.add(key)
        unique.append((kind, val, make_url(kind, val), key))

    text = text or ""
    for m in LINK_RE.finditer(text):
        invite = m.group("tg") or m.group("priv")
        if invite:
            add("private", invite)
        else:
            name = m.group("pub")
            if name.lower() not in RESERVED:
                add("public", name)
    for line in text.splitlines():  # akeli @username wali line
        m = AT_LINE_RE.match(line.strip())
        if m:
            add("public", m.group(1))
    return unique, repeats


def collect_text(message):
    """Message ka text + hidden hyperlinks + button URLs ek string me."""
    parts = [getattr(message, "raw_text", None) or ""]
    try:
        for entity, _ in message.get_entities_text():
            url = getattr(entity, "url", None)
            if url:
                parts.append(url)
    except Exception:
        pass
    try:
        for row in message.buttons or []:
            for button in row:
                url = getattr(button, "url", None)
                if url:
                    parts.append(url)
    except Exception:
        pass
    return "\n".join(parts)
