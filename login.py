# Run ONCE on your own computer: pip install telethon ; python login.py
# Enter api_id/api_hash from my.telegram.org, then your phone and the code Telegram sends.
# It prints TG_SESSION - put it into GitHub Secrets. Never share it: it is full access to your account.
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
api_id = int(input("api_id: ")); api_hash = input("api_hash: ")
with TelegramClient(StringSession(), api_id, api_hash) as c:
    print("\nTG_SESSION =", c.session.save())
