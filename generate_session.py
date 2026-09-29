import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("TELEGRAM_API_ID: ").strip())
api_hash = input("TELEGRAM_API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nYour TELEGRAM_SESSION string:\n")
    print(client.session.save())
    print("\nKEEP THIS SECRET. Do not send it to anyone.")
