"""Re-render captions of already published channel posts with the current format and current offer data.
python edit.py N [BELOW]  -> last N channel messages (only ids < BELOW if given) that link a Content Rewards campaign.
Edits are silent (no notifications). Offers CR no longer lists as active are left as they are."""
import asyncio, sys
import main as M

async def run(n, below=0):
    from telethon.errors import MessageNotModifiedError, FloodWaitError
    camps = M.newest(); M.org_stats(camps)
    by_id = {o["id"]: o for o in camps if M.eligible(o)}
    ok = same = miss = fail = 0
    async with M.tg_client() as cl:
        ch = await cl.get_entity(M.CFG["channel"])
        async for msg in cl.iter_messages(ch, limit=n, max_id=below):
            urls = [getattr(e, "url", "") or "" for e in (msg.entities or [])] + [msg.message or ""]
            cid = next((m.group(1) for u in urls for m in [M.CAMP_RE.search(u)] if m), None)
            if not cid: continue
            o = by_id.get(cid)
            if not o:
                print("not in live list, skip", msg.id, cid); miss += 1; continue
            det = M.detail(cid)
            if det is None:
                print("detail gone, skip", msg.id, o["name"][:50]); miss += 1; continue
            try: cap = M.caption(o, det)
            except Exception as e:
                print("caption fail", msg.id, o["name"][:40], repr(e)[:150]); fail += 1; continue
            for _ in range(3):
                try:
                    await cl.edit_message(ch, msg.id, cap, parse_mode="html", link_preview=False)
                    print("edited", msg.id, o["name"][:60]); ok += 1; break
                except MessageNotModifiedError:
                    same += 1; break
                except FloodWaitError as e:
                    print("flood wait", e.seconds, "s"); await asyncio.sleep(e.seconds + 2)
                except Exception as e:
                    print("fail", msg.id, o["name"][:40], str(e)[:150]); fail += 1; break
            await asyncio.sleep(6)
    print(f"edited: {ok}, unchanged: {same}, skipped (offer not live): {miss}, failed: {fail}")

if __name__ == "__main__":
    asyncio.run(run(int(sys.argv[1]) if len(sys.argv) > 1 else 50, int(sys.argv[2]) if len(sys.argv) > 2 else 0))
