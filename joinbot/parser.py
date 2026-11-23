"""Extract Telegram channel/group links from free text."""
import re
from dataclasses import dataclass
from typing import Iterable, List

INVITE = "invite"
PUBLIC = "public"

# t.me/+HASH, t.me/joinchat/HASH
_INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/(?:\+|joinchat/)([A-Za-z0-9_\-]+)",
    re.I,
)
# tg://join?invite=HASH
_TG_INVITE_RE = re.compile(r"tg://join\?invite=([A-Za-z0-9_\-]+)", re.I)
# t.me/username  (also t.me/s/username, optional /123 post id)
_PUBLIC_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/(?:s/)?"
    r"(?!joinchat/|\+)([A-Za-z][A-Za-z0-9_]*)(?:/\d+)?",
    re.I,
)
# tg://resolve?domain=username
_TG_RESOLVE_RE = re.compile(r"tg://resolve\?domain=([A-Za-z][A-Za-z0-9_]*)", re.I)
# @username (not part of an e-mail / url)
_AT_RE = re.compile(r"(?<![\w/@.])@([A-Za-z][A-Za-z0-9_]{3,31})")

# t.me/<word> paths that are not channels
_RESERVED = {
    "c", "s", "joinchat", "addstickers", "addemoji", "addtheme", "addlist",
    "share", "proxy", "socks", "login", "setlanguage", "confirmphone",
    "bg", "iv", "invoice", "boost", "giftcode", "m", "contact", "web",
}

MIN_INVITE_LEN = 16  # real invite hashes are 16-22 chars


@dataclass(frozen=True)
class ParsedLink:
    kind: str  # "invite" | "public"
    ref: str  # invite hash or username (original case)
    key: str  # dedupe key
    original: str  # text as found in the message


def _make(kind: str, ref: str, original: str) -> ParsedLink:
    key = ("i:" + ref) if kind == INVITE else ("u:" + ref.lower())
    return ParsedLink(kind, ref, key, original)


def extract_links(text: str, extra_urls: Iterable[str] = ()) -> List[ParsedLink]:
    """Return unique links found in `text` (+ hidden urls), in order of appearance."""
    if extra_urls:
        text = text + "\n" + "\n".join(extra_urls)
    found = []  # (position, ParsedLink)

    for m in _INVITE_RE.finditer(text):
        found.append((m.start(), _make(INVITE, m.group(1), m.group(0))))
    for m in _TG_INVITE_RE.finditer(text):
        found.append((m.start(), _make(INVITE, m.group(1), m.group(0))))
    for m in _PUBLIC_RE.finditer(text):
        name = m.group(1)
        if name.lower() in _RESERVED:
            continue
        found.append((m.start(), _make(PUBLIC, name, m.group(0))))
    for m in _TG_RESOLVE_RE.finditer(text):
        found.append((m.start(), _make(PUBLIC, m.group(1), m.group(0))))
    for m in _AT_RE.finditer(text):
        found.append((m.start(), _make(PUBLIC, m.group(1), m.group(0))))

    found.sort(key=lambda x: x[0])
    seen, out = set(), []
    for _, link in found:
        if link.key in seen:
            continue
        seen.add(link.key)
        out.append(link)
    return out


def local_validation_error(link: ParsedLink):
    """Cheap offline check. Returns an error string if the link is surely invalid."""
    if link.kind == INVITE:
        if len(link.ref) < MIN_INVITE_LEN:
            return "Invite hash too short"
    else:
        if len(link.ref) < 5:
            return "Username too short (min 5 chars)"
        if len(link.ref) > 32:
            return "Username too long"
        if link.ref.endswith("_") or "__" in link.ref:
            return "Invalid username format"
    return None
