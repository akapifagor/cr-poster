# Send yourself (Saved Messages) ONE message like:  x <X emoji> tiktok <TikTok emoji> instagram <IG emoji> youtube <YT emoji>
# (labels optional; without labels the order X TikTok Instagram YouTube is used). Then run this (or the "Emoji ids" workflow):
# it reads the newest Saved Message with custom emoji and writes ids into config.json "platform_emoji".
import os, re, json, sys
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityCustomEmoji
HERE = os.path.dirname(os.path.abspath(__file__)); CFGP = os.path.join(HERE, "config.json")
ALIAS = {"x": "x", "twitter": "x", "tw": "x", "tiktok": "tiktok", "tt": "tiktok", "instagram": "instagram", "ig": "instagram", "inst": "instagram", "insta": "instagram", "youtube": "youtube", "yt": "youtube"}
env = os.environ.get
with TelegramClient(StringSession(env("TG_SESSION") or input("TG_SESSION: ")), int(env("TG_API_ID") or input("api_id: ")), env("TG_API_HASH") or input("api_hash: ")) as c:
    msgs = c.get_messages("me", limit=30)
    order_env = [k.strip() for k in (env("EMOJI_ORDER") or "").split(",") if k.strip()]
    if order_env:  # emoji sent as separate messages, oldest -> newest in this order
        solo = []
        for m in msgs:  # newest first
            es = [e for e in m.entities or [] if isinstance(e, MessageEntityCustomEmoji)]
            if len(es) == 1 and len(m.raw_text.strip()) <= 4: solo.append((m, es[0]))
            elif solo: break
        solo = solo[:len(order_env)][::-1]
        res = {k: str(e.document_id) for k, (m, e) in zip(order_env, solo)}
        for k, (m, e) in zip(order_env, solo): print(k, e.document_id, repr(m.raw_text), m.date)
        print("platform_emoji =", res)
        cfg = json.load(open(CFGP, encoding="utf-8")); cfg["platform_emoji"] = {**(cfg.get("platform_emoji") or {}), **res}
        json.dump(cfg, open(CFGP, "w", encoding="utf-8"), ensure_ascii=False, indent=2); open(CFGP, "a").write("\n"); sys.exit()
    m = next((m for m in msgs if any(isinstance(e, MessageEntityCustomEmoji) for e in m.entities or [])), None)
    if not m: sys.exit("No Saved Message with custom emoji found")
    ents = [e for e in m.entities if isinstance(e, MessageEntityCustomEmoji)]
    # telethon offsets are UTF-16; convert text accordingly
    t16 = m.raw_text.encode("utf-16-le"); res = {}; order = ["x", "tiktok", "instagram", "youtube"]; prev = 0
    for i, e in enumerate(ents):
        before = t16[prev * 2:e.offset * 2].decode("utf-16-le", "ignore").lower()
        words = re.findall(r"[a-z]+", before); key = ALIAS.get(words[-1]) if words else None
        if not key: key = next((k for k in order if k not in res), None)
        if key: res[key] = str(e.document_id)
        prev = e.offset + e.length
    print("platform_emoji =", res)
    cfg = json.load(open(CFGP, encoding="utf-8")); cfg["platform_emoji"] = {**(cfg.get("platform_emoji") or {}), **res}
    json.dump(cfg, open(CFGP, "w", encoding="utf-8"), ensure_ascii=False, indent=2); open(CFGP, "a").write("\n")
