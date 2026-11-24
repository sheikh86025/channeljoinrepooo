"""Ek baar chalao: apne userbot account ka SESSION_STRING nikalne ke liye.
Ye string account ka poora access deti hai — kisi ko mat dena, GitHub par mat daalna."""
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("API_ID: ").strip())
API_HASH = input("API_HASH: ").strip()

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nSESSION_STRING:\n")
    print(client.session.save())
