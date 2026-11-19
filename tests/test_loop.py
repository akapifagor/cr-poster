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
        self.sent, self.history, self.fail_sends, self.alerts = [], list(history), fail_sends, []
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

if __name__ == "__main__":
    unittest.main()
