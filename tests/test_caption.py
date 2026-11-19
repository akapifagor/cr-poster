"""Offline tests for caption building and offer selection on real Content Rewards data (tests/fixtures.json, 2026-11-19).
Run: python -m unittest discover -s tests -v"""
import json, os, sys, unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.pop("GEMINI_API_KEY", None)  # rules only: no network in tests
os.environ.pop("GITHUB_ACTIONS", None)
import main as M

FX = json.load(open(os.path.join(HERE, "fixtures.json"), encoding="utf-8"))
M.org_stats([f["offer"] for f in FX.values()])

def cap(key):
    return M.caption(FX[key]["offer"], FX[key]["detail"])

def rate_line(c, plat):
    return next((l for l in c.split("\n") if f"</tg-emoji> {plat} - " in l or l.startswith(f"{M.PLAT_FALLBACK.get(plat, '')} {plat} - ")), "")

class Geo(unittest.TestCase):
    def test_rest_of_world_rate_is_shown(self):
        # TikTok/YouTube: $2.00 everywhere except BD/IN/PK (listing rateCents is 0, rate lives in geoRates.restOfWorld)
        c = cap("steam")
        self.assertIn("TikTok - <b>$2.00</b>, кроме 🇧🇩🇮🇳🇵🇰", c)
        self.assertIn("YouTube Shorts - <b>$2.00</b>, кроме 🇧🇩🇮🇳🇵🇰", c)
        self.assertIn("Instagram - <b>$1.50</b>", c)
        self.assertNotIn("Ставка зависит от гео", c)

    def test_all_platforms_geo_not_dropped(self):
        c = cap("stranger")
        self.assertNotIn("ставки в оффере", c)
        for p in ("TikTok", "Instagram", "YouTube Shorts"):
            self.assertIn(f"{p} - <b>$2.00</b>, кроме 🇧🇩🇮🇳🇵🇰", c)

    def test_only_listed_countries_paid(self):
        c = cap("spanish")
        self.assertIn("TikTok - <b>$2.00</b> 🇲🇽🇦🇷, остальной мир не оплачивается", c)
        self.assertNotIn("spanish", c)  # brand label is vague, flags are not

    def test_geo_tiers_without_geopriced_flag(self):
        o = FX["talking"]["offer"]
        self.assertFalse(o["geoPriced"])
        c = cap("talking")
        self.assertIn("<b>$2.50</b> 🇺🇸", c)
        self.assertIn("<b>$0.75</b> остальной мир", c)

    def test_many_countries(self):
        c = cap("jersey")
        line = rate_line(c, "TikTok")
        self.assertIn("остальной мир не оплачивается", line)
        self.assertIn("🇺🇸", line)

    def test_per_platform_tier_rates(self):
        c = cap("france")
        self.assertIn("TikTok - <b>$5.00</b> 🇫🇷, остальной мир не оплачивается", c)
        self.assertIn("Instagram - <b>$3.00</b> 🇫🇷, остальной мир не оплачивается", c)
        self.assertIn("Рекламодатель", c)  # not cut by the length guard

class PayoutTypes(unittest.TestCase):
    def test_pool_conditions(self):
        c = cap("pool")
        self.assertIn("Пул $10,000", c)
        self.assertIn("от 750K просмотров суммарно", c)
        self.assertIn("клип засчитывается от 1K просмотров", c)

    def test_per_post_submission_limit(self):
        c = cap("perpost")
        self.assertIn("Фикс за пост:</b> $430", c)
        self.assertIn("<b>Лимит:</b> 1 пост на креатора", c)

    def test_min_views_formatting(self):
        c = cap("bigmin")
        self.assertRegex(c, r"оплата от \d+(\.\d)?K просмотров")
        self.assertNotRegex(c, r"\d\.\d{3,}K")

    def test_simple_cpm(self):
        c = cap("ruckus")
        self.assertIn("Ставки за 1K просмотров", c)
        self.assertIn("TikTok - <b>$2.00</b>", c)
        self.assertIn("оплата от 5K просмотров", c)

class Helpers(unittest.TestCase):
    def test_kviews(self):
        for n, s in [(33333.3, "33.3K"), (1333.3, "1.33K"), (666.7, "670"), (1000, "1K"), (2500, "2.5K"),
                     (250000, "250K"), (999999, "1M"), (2_000_000, "2M"), (50, "50"), (200, "200")]:
            self.assertEqual(M.kviews(n), s, n)

    def test_plural(self):
        self.assertEqual([M.plural(n, "пост", "поста", "постов") for n in (1, 2, 5, 11, 21, 22, 25)],
                         ["пост", "поста", "постов", "постов", "пост", "поста", "постов"])

    def test_adult(self):
        f = lambda k: M.adult(M.brief(FX[k]["offer"], FX[k]["detail"]))
        self.assertFalse(f("clickoptions"))  # "no casino, gambling or memecoin pages" is a ban, not a gambling offer
        self.assertFalse(f("directoricy"))   # "chat roulette"
        self.assertTrue(f("gavin"))
        self.assertTrue(f("bitline"))
        self.assertFalse(M.adult("limited slots available, what's at stake for you"))
        self.assertTrue(M.adult("clip the stake.com slots stream"))

    def test_clean_niches(self):
        self.assertEqual(M.clean_niches(["Игры: прочее", "Музыка", "Игры: GTA 6", "Здоровье и фитнес", "Подкасты", "AI"]),
                         ["Музыка", "Игры: GTA 6", "Подкасты"])

    def test_captions_are_valid_and_fit(self):
        for k, f in FX.items():
            c = M.caption(f["offer"], f["detail"])
            self.assertLessEqual(M.visible_len(c), 1024, k)
            self.assertIn("Открыть оффер", c, k)
            self.assertIn("A.k.a Pifagor", c, k)  # signature never cut

class Selection(unittest.TestCase):
    def offer(self, oid, hours_ago, spent=0):
        t = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return {"id": oid, "status": "active", "private": False, "listedAt": t, "budgetCents": 1000, "metrics": {"budgetSpentCents": spent}}

    def test_select(self):
        camps = [self.offer("new2", 0.1), self.offer("new1", 1), self.offer("full", 2, spent=900), self.offer("old", 72), self.offer("known", 3)]
        camps.append({**self.offer("paused", 0.2), "status": "paused"})
        seen = {"known"}
        new = M.select(camps, seen)
        self.assertEqual([o["id"] for o in new], ["new1", "new2"])  # oldest first
        self.assertTrue({"old", "full"} <= seen)  # stale / nearly spent are silenced
        self.assertNotIn("paused", seen)

    def test_git_sync_noop_outside_ci(self):
        self.assertTrue(M.git_sync(set()))

if __name__ == "__main__":
    unittest.main()
