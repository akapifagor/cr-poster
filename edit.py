"""Re-render captions of already published channel posts with the current format.
python edit.py N   -> last N channel messages that link a Content Rewards campaign (text only, no new notifications)."""
import asyncio, os, re, sys
import main as M

async def run(n):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import MessageNotModifiedError
    camps = M.newest(); M.org_stats(camps)
    by_id = {o["id"]: o for o in camps}
    ok = same = miss = 0
    async with TelegramClient(StringSession(os.environ["TG_SESSION"]), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]) as cl:
        ch = await cl.get_entity(M.CFG["channel"])
        async for msg in cl.iter_messages(ch, limit=n):
            urls = [getattr(e, "url", "") or "" for e in (msg.entities or [])] + [msg.message or ""]
            m = next((re.search(r"contentrewards\.com/c/campaigns/([0-9a-f-]{36})", u) for u in urls if "contentrewards.com/c/campaigns/" in u), None)
            if not m: continue
            cid = m.group(1); o = by_id.get(cid)
            if not o:
                d = M.get(f"{M.API}/{cid}").get("data") or {}
                print("not in live list, skip", msg.id, (d.get("name") or cid)[:50]); miss += 1; continue
            det = M.get(f"{M.API}/{cid}").get("data") or {}
            cap = M.caption(o, det)
            try:
                await cl.edit_message(ch, msg.id, cap, parse_mode="html", link_preview=False)
                print("edited", msg.id, o["name"][:60]); ok += 1
            except MessageNotModifiedError:
                same += 1
            except Exception as e:
                print("fail", msg.id, o["name"][:40], str(e)[:150])
            await asyncio.sleep(3)
    print(f"edited: {ok}, unchanged: {same}, skipped (offer gone): {miss}")

if __name__ == "__main__":
    asyncio.run(run(int(sys.argv[1]) if len(sys.argv) > 1 else 50))
