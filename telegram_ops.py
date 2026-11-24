"""Telegram (Telethon) se asli join karne wala hissa. Worker isi ko call karta hai."""
from telethon import utils
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel


def _result(status, chat=None, detail=""):
    title, cid = "", ""
    if chat is not None:
        title = getattr(chat, "title", "") or ""
        try:
            cid = str(utils.get_peer_id(chat))
        except Exception:
            cid = ""
    return {"status": status, "detail": detail, "title": title, "channel_id": cid}


class TelegramOps:
    def __init__(self, client):
        self.client = client

    async def join(self, kind, val):
        """Errors (FloodWait, invalid invite, etc.) worker ko propagate hote hain."""
        if kind == "private":
            # seedha import: extra check call nahi, isliye tez.
            # Already member => UserAlreadyParticipantError, approval wala => InviteRequestSentError
            upd = await self.client(ImportChatInviteRequest(val))
            chats = getattr(upd, "chats", None)
            return _result("joined", chats[0] if chats else None)

        try:
            entity = await self.client.get_entity(val)
        except ValueError:
            return _result("not_found", detail="username not found")
        if not isinstance(entity, Channel):
            return _result("not_found", detail="not a channel/group (user or bot)")
        if not getattr(entity, "left", True):  # pehle se member
            return _result("already_joined", entity)
        await self.client(JoinChannelRequest(entity))
        return _result("joined", entity)

    async def count_joined(self):
        n = 0
        async for dialog in self.client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, Channel) and not getattr(entity, "left", False):
                n += 1
        return n
