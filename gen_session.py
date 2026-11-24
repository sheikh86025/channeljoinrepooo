"""LOCAL machine pe ek baar chalao: python gen_session.py
Jo SESSION_STRING print hoga use Railway variables me daalo.
WARNING: ye string = aapke account ka full access. Kisi ko mat do."""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        # phone, OTP (aur 2FA password) terminal me poochega
        print("\nSESSION_STRING:\n")
        print(client.session.save())


asyncio.run(main())
