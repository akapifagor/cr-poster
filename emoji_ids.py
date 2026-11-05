# Send yourself (Saved Messages) one message with the custom emoji in this order: X TikTok Instagram YouTube
# then run: python emoji_ids.py  -> prints ids for config.json "platform_emoji"
import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityCustomEmoji
with TelegramClient(StringSession(os.environ.get("TG_SESSION") or input("TG_SESSION: ")), int(input("api_id: ")), input("api_hash: ")) as c:
    m = c.get_messages("me", limit=1)[0]
    ids = [e.document_id for e in m.entities or [] if isinstance(e, MessageEntityCustomEmoji)]
    print(dict(zip(["x", "tiktok", "instagram", "youtube"], map(str, ids))))
