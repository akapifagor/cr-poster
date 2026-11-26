"""Posting flow with a fake Telegram client: dedup against the channel, posting gap, seen.json persistence, error handling."""
import asyncio, json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GITHUB_ACTIONS", None)
import main as M

FX = json.load(open(os.path.join(HERE, "fixtures.json"), encoding="utf-8"))

class FakeClient:
    def __init__(self, history=(), fail_sends=0):
        self.sent, self.history, self.fail_sends, self.alerts, self.edits = [], list(history), fail_sends, [], []
    def iter_messages(self, ch, limit=None):
        async def gen():
            for m in sorted(self.history, key=lambda m: -getattr(m, "id", 0))[:limit]: yield m
        return gen()
    async def edit_message(self, ch, mid, text, parse_mode=None, link_preview=None): self.edits.append((mid, text))
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get_entity(self, x): return "channel"
    async def get_messages(self, ch, limit=60): return self.history
    async def __call__(self, req): return SimpleNamespace(messages=[])
    def is_connected(self): return True
    async def connect(self): pass
    async def _send(self, ch, cap, schedule):
        if ch == "me": self.alerts.append(cap); return
        if self.fail_sends: self.fail_sends -= 1; raise ConnectionError("telegram down")
        self.sent.append((cap, schedule))
    async def send_file(self, ch, f, caption=None, parse_mode=None, schedule=None): await self._send(ch, caption, schedule)
    async def send_message(self, ch, text, parse_mode=None, link_preview=None, schedule=None): await self._send(ch, text, schedule)

def fresh(o, minutes_ago):
    return {**o, "listedAt": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "metrics": {**(o.get("metrics") or {}), "budgetSpentCents": 0}}

class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = {"SEEN": M.SEEN, "newest": M.newest, "detail": M.detail, "banner": M.banner, "tg_client": M.tg_client}
        M.SEEN = os.path.join(self.tmp, "seen.json")
        self.offers = [fresh(FX[k]["offer"], m) for k, m in (("ruckus", 3), ("pool", 4), ("steam", 5))]  # API order: newest first
        dets = {FX[k]["offer"]["id"]: FX[k]["detail"] for k in FX}
        M.newest = lambda seen=None, pages=20: self.offers
        M.detail = lambda cid: dets.get(cid)
        M.banner = lambda o: None
        M._alerted.clear()

    def tearDown(self):
        for k, v in self.patches.items(): setattr(M, k, v)

    def run_once(self, client, seen=()):
        M.save_seen(set(seen))
        M.tg_client = lambda: client
        asyncio.run(M.run(False))
        return M.load_seen()

    def test_posts_new_offers_oldest_first_with_gap(self):
        cl = FakeClient()
        seen = self.run_once(cl)
        self.assertEqual(len(cl.sent), 3)
        self.assertIn("SEGA - Steam Black Friday", cl.sent[0][0])  # listed 5 min ago -> first
        self.assertIsNone(cl.sent[0][1])  # first goes out now, next ones are scheduled post_gap_minutes apart
        gap = (cl.sent[2][1] - cl.sent[1][1]).total_seconds() / 60
        self.assertAlmostEqual(gap, float(M.CFG.get("post_gap_minutes", 3)), delta=0.1)
        self.assertTrue({o["id"] for o in self.offers} <= seen)

    def test_already_posted_in_channel_is_not_reposted(self):
        url = f"https://contentrewards.com/c/campaigns/{self.offers[-1]['id']}"
        msg = SimpleNamespace(entities=[SimpleNamespace(url=url)], message="", date=datetime.now(timezone.utc))
        cl = FakeClient(history=[msg])
        self.run_once(cl)  # seen.json lost this id, the channel still has it
        self.assertEqual(len(cl.sent), 2)
        self.assertFalse(any("Steam Black Friday" in c for c, _ in cl.sent))

    def test_send_failure_keeps_offer_unseen_and_saves_progress(self):
        cl = FakeClient(fail_sends=0)
        orig = cl._send
        calls = {"n": 0}
        async def flaky(ch, cap, schedule):
            calls["n"] += 1
            if calls["n"] == 2: raise ConnectionError("telegram down")
            await orig(ch, cap, schedule)
        cl._send = flaky
        with self.assertRaises(ConnectionError):
            self.run_once(cl)
        seen = M.load_seen()
        self.assertIn(self.offers[2]["id"], seen)  # oldest, posted before the failure: saved
        self.assertNotIn(self.offers[1]["id"], seen)  # failed: retried next cycle
        cl2 = FakeClient()
        self.run_once(cl2, seen)
        self.assertEqual(len(cl2.sent), 2)  # the rest goes out, nothing twice

    def test_timeout_after_delivery_is_not_resent(self):
        # send raised (timeout) although Telegram delivered the post: the retry must find it in the channel
        cl = FakeClient()
        o = self.offers[-1]
        async def delivered_then_timeout(ch, cap, schedule):
            url = f"https://contentrewards.com/c/campaigns/{o['id']}"
            cl.history.append(SimpleNamespace(entities=[SimpleNamespace(url=url)], message="", date=datetime.now(timezone.utc)))
            raise asyncio.TimeoutError()
        cl._send = delivered_then_timeout
        seen, st = set(), M.Run()
        async def go():
            with self.assertRaises(asyncio.TimeoutError):
                await M.post_new(cl, "channel", [o], seen, st)
            self.assertNotIn(o["id"], seen)
            await M.post_new(cl, "channel", [o], seen, st)  # next cycle
        asyncio.run(go())
        self.assertIn(o["id"], seen)
        self.assertEqual(len(cl.history), 1)  # delivered once, no duplicate

    def test_gap_counts_from_the_actual_send_time(self):
        # a FloodWait or a slow upload delays the first post: the next one still has to wait post_gap_minutes after it
        class Clock(datetime):
            t = datetime(2026, 11, 20, 15, 26, tzinfo=timezone.utc)
            @classmethod
            def now(cls, tz=None): return cls.t
        self.patches["datetime"] = M.datetime
        M.datetime = Clock
        cl = FakeClient()
        orig = cl._send
        async def slow_first(ch, cap, schedule):
            await orig(ch, cap, schedule)
            if len(cl.sent) == 1: Clock.t += timedelta(minutes=5)  # e.g. a 245 s FloodWait inside send
        cl._send = slow_first
        asyncio.run(M.post_new(cl, "channel", self.offers[::-1][:2], set(), M.Run()))
        gap = float(M.CFG.get("post_gap_minutes", 3))
        self.assertIsNotNone(cl.sent[1][1])  # scheduled, not fired right after the delayed first post
        self.assertGreaterEqual(cl.sent[1][1], Clock.t + timedelta(minutes=gap) - timedelta(seconds=1))


def post_msg(mid, o, det, hours_ago=1, extra_line=None):
    """a channel message as Telegram returns it: visible text + entities of the caption the bot built"""
    from telethon.extensions import html as tg_html
    cap = M.caption(o, det)
    if extra_line:
        first, _, rest = cap.partition("\n"); cap = f"{first}\n{extra_line}\n{rest}"
    text, ents = tg_html.parse(cap)
    return SimpleNamespace(id=mid, message=text, entities=ents, date=datetime.now(timezone.utc) - timedelta(hours=hours_ago))

class Refresh(unittest.TestCase):
    """Advertisers change rates, caps and limits after launch and pause offers: recent posts are kept true to CR."""
    def setUp(self):
        self.saved = {"detail": M.detail, "cfg": dict(M.CFG)}
        M.CFG.update({"refresh_hours": 72, "refresh_max_edits": 8, "refresh_edit_gap_seconds": 0})
        self.o = json.loads(json.dumps(FX["ruckus"]["offer"])); self.det = json.loads(json.dumps(FX["ruckus"]["detail"]))
        self.dets = {self.o["id"]: self.det}
        M.detail = lambda cid: self.dets.get(cid)

    def tearDown(self):
        M.detail = self.saved["detail"]; M.CFG.clear(); M.CFG.update(self.saved["cfg"])

    def refresh(self, cl, live):
        return asyncio.run(M.refresh_posts(cl, "channel", live))

    def test_unchanged_post_is_left_alone(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det)])
        self.refresh(cl, {self.o["id"]: self.o})
        self.assertEqual(cl.edits, [])

    def test_spent_share_and_advertiser_stats_do_not_trigger_edits(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det)])
        o2 = json.loads(json.dumps(self.o)); o2.setdefault("metrics", {})["budgetSpentCents"] = (o2.get("budgetCents") or 0) // 2
        self.refresh(cl, {self.o["id"]: o2})
        self.assertEqual(cl.edits, [])

    def test_post_is_rerendered_when_the_rate_changes(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det)])
        o2 = json.loads(json.dumps(self.o))
        for p in o2["payouts"]: p["rateCents"] = (p.get("rateCents") or 0) + 50
        self.refresh(cl, {self.o["id"]: o2})
        self.assertEqual(len(cl.edits), 1)
        mid, text = cl.edits[0]
        self.assertEqual(mid, 10)
        self.assertIn(M.money(o2["payouts"][0]["rateCents"], True), text)
        self.assertIn("Условия обновлены", text)

    def test_paused_offer_is_marked_and_keeps_its_custom_emoji(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det)])
        self.dets[self.o["id"]] = {**self.det, "status": "paused"}
        self.refresh(cl, {})
        self.assertEqual(len(cl.edits), 1)
        text = cl.edits[0][1]
        self.assertIn("⛔ <b>Оффер на паузе</b>", text.split("\n")[1])
        self.assertIn("<tg-emoji emoji-id=", text)

    def test_offer_gone_from_cr_is_marked_closed(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det)])
        self.dets.clear()  # detail 403/404
        self.refresh(cl, {})
        self.assertIn("⛔ <b>Оффер закрыт</b>", cl.edits[0][1])

    def test_active_offer_missing_from_the_list_is_not_marked(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det)])
        self.dets[self.o["id"]] = {**self.det, "status": "active"}
        self.refresh(cl, {})
        self.assertEqual(cl.edits, [])

    def test_closed_mark_is_added_once(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det, extra_line="⛔ <b>Оффер на паузе</b>")])
        self.dets[self.o["id"]] = {**self.det, "status": "paused"}
        self.refresh(cl, {})
        self.assertEqual(cl.edits, [])

    def test_reopened_offer_loses_the_closed_mark(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det, extra_line="⛔ <b>Оффер на паузе</b>")])
        self.refresh(cl, {self.o["id"]: self.o})
        self.assertEqual(len(cl.edits), 1)
        self.assertNotIn("⛔", cl.edits[0][1])

    def test_old_posts_are_not_touched(self):
        cl = FakeClient(history=[post_msg(10, self.o, self.det, hours_ago=100)])
        self.dets.clear()
        self.refresh(cl, {})
        self.assertEqual(cl.edits, [])

    def test_manual_post_with_a_campaign_link_is_never_edited(self):
        from telethon.extensions import html as tg_html
        text, ents = tg_html.parse(f'Смотрите какой оффер: <a href="https://contentrewards.com/c/campaigns/{self.o["id"]}">ссылка</a>')
        cl = FakeClient(history=[SimpleNamespace(id=10, message=text, entities=ents, date=datetime.now(timezone.utc))])
        self.dets.clear()
        self.refresh(cl, {})
        self.assertEqual(cl.edits, [])

    def test_edits_per_pass_are_capped(self):
        M.CFG["refresh_max_edits"] = 2
        self.dets.clear()
        cl = FakeClient(history=[post_msg(i, self.o, self.det) for i in (10, 11, 12)])
        self.refresh(cl, {})
        self.assertEqual(len(cl.edits), 2)

if __name__ == "__main__":
    unittest.main()
