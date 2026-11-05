"""Content Rewards -> Telegram channel poster (userbot, custom emoji).
Runs once per call (GitHub Actions cron every 30 min). New campaigns = ids not in seen.json.
"""
import io, json, os, re, sys, time, asyncio, html
import requests

API = "https://contentrewards.com/api/campaign/campaigns"
HDR = {"x-cr-app": "creators", "user-agent": "Mozilla/5.0"}
CDN = "https://crusercontent.com/"
HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "seen.json")
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))

NICHE = {  # CR category id -> RU label (unknown ids fall back to CR's English name)
 "artificial-intelligence": "AI", "ai-tools": "AI-сервисы", "ai-video": "AI-видео", "technology": "Технологии",
 "software": "Софт", "saas": "SaaS", "developer-tools": "Инструменты для разработчиков", "productivity-tools": "Продуктивность",
 "productivity": "Продуктивность", "gadgets": "Гаджеты", "app": "Приложения", "mobile-app": "Мобильные приложения",
 "ios-app": "iOS-приложения", "roblox": "Roblox", "minecraft": "Minecraft", "fortnite": "Fortnite", "gta": "GTA",
 "gaming": "Игры", "pc-gaming": "PC-игры", "mobile-gaming": "Мобильные игры", "streamer": "Стримеры", "twitch": "Twitch",
 "kick": "Kick", "youtuber": "Ютуберы", "influencer": "Инфлюенсеры", "content-creator": "Контент-мейкеры",
 "fan-page": "Фан-страницы", "celebrity": "Знаменитости", "entertainment": "Развлечения", "comedy": "Юмор",
 "reactions": "Реакции", "storytime": "Сторитайм", "music": "Музыка", "dj-electronic": "DJ и электроника",
 "sound-campaign": "Продвижение трека", "artist-promo": "Промо артиста", "podcast": "Подкасты",
 "business-podcast": "Бизнес-подкасты", "comedy-podcast": "Юмор-подкасты", "movie-tv-show": "Кино и сериалы",
 "movie-clips": "Нарезки фильмов", "film-trailers": "Трейлеры", "cartoons": "Мультфильмы и анимация",
 "documentary": "Документалки", "personal-brand": "Личный бренд", "personal-development": "Саморазвитие",
 "coaching-consulting": "Коучинг", "online-course": "Онлайн-курсы", "education": "Образование",
 "language-learning": "Изучение языков", "business": "Бизнес", "entrepreneur": "Предпринимательство",
 "side-hustle": "Подработка", "marketing": "Маркетинг", "seo": "SEO", "ecommerce": "E-commerce",
 "dropshipping": "Дропшиппинг", "consumer-brand": "Потребительский бренд", "product": "Товар",
 "beverage-brand": "Напитки", "finance": "Финансы", "personal-finance": "Личные финансы",
 "banking-fintech": "Банки и финтех", "credit-score": "Кредиты", "trading": "Трейдинг", "day-trading": "Дейтрейдинг",
 "forex": "Форекс", "crypto": "Крипта", "crypto-trading": "Крипто-трейдинг", "memecoins": "Мемкоины",
 "real-estate": "Недвижимость", "rental-property": "Аренда недвижимости", "gambling": "Гемблинг 18+",
 "casino": "Казино 18+", "poker": "Покер 18+", "sports": "Спорт", "football-soccer": "Футбол", "fitness": "Фитнес",
 "health": "Здоровье", "health-wellness": "Здоровье", "weight-loss": "Похудение", "beauty": "Бьюти",
 "fashion": "Мода", "luxury-fashion": "Люкс-мода", "lifestyle": "Лайфстайл", "travel": "Путешествия",
 "camping": "Кемпинг", "outdoors": "Активный отдых", "automotive": "Авто", "pets": "Питомцы",
 "home-living": "Дом", "parenting-family": "Семья", "relationships-dating": "Отношения и знакомства",
 "art-design": "Арт и дизайн", "events": "Ивенты", "politics": "Политика", "news-politics": "Новости и политика",
 "christian": "Христианство", "faith-spirituality": "Вера", "food": "Еда",
}
ADULT = r"\b(casino|gambl\w*|slots?|roulette|betting|sportsbook|stake\.com|roobet|shuffle\.com|poker|blackjack)\b"
CTYPE = {"clipping": "Клиппинг", "youtube-long-form": "Длинные видео YouTube", "ugc-with-face": "UGC с лицом", "ugc-faceless": "UGC без лица",
         "editing": "Монтаж", "slideshow": "Слайдшоу", "meme": "Мемы", "repost": "Репосты"}
PLAT = {"x": "X", "tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube Shorts", "facebook": "Facebook",
        "snapchat": "Snapchat", "threads": "Threads"}
PLAT_FALLBACK = {"x": "𝕏", "tiktok": "🎵", "instagram": "📸", "youtube": "▶️", "facebook": "📘", "snapchat": "👻", "threads": "🧵"}

def get(url, **kw):
    for i in range(4):
        r = requests.get(url, headers=HDR, timeout=30, **kw)
        if r.status_code == 200: return r.json()
        time.sleep(3 * (i + 1))
    r.raise_for_status()

def newest(pages=10):
    out, cur = [], None
    for _ in range(pages):
        q = {"limit": 100, "sortBy": "newest"}
        if cur: q["cursor"] = cur
        d = get(API + "/discover", params=q)
        out += d["data"]
        cur = (d.get("pagination") or {}).get("nextCursor")
        if not cur: break
    return out

def money(c, rate=False):
    v = c / 100
    return f"${v:,.2f}" if rate or v != int(v) and v < 100 else f"${v:,.0f}"

def emoji(p):
    fb = PLAT_FALLBACK.get(p, "•")
    eid = (CFG.get("platform_emoji") or {}).get(p)
    return f'<tg-emoji emoji-id="{eid}">⭐</tg-emoji>' if eid else fb  # inner text must be a real emoji

# Footage detection (heuristic on the offer description; EN + common IT/ES/FR/PT/DE words)
FOOT_GIVE = r"(source footage|our footage|(footage|videos?|clips?|episodes?|assets?|content|materials?) (is |are )?(provided|supplied|attached|included|below|linked|in the (drive|folder|brief|link))|(provided|supplied|official|attached) (footage|videos?|clips?|episodes?|assets?|content|materials?|b-?roll)|(use|clip|edit) (the|our) \d* ?(official )?(videos?|clips?|footage|episodes?)( below)?|raw footage|google drive|drive\.google|dropbox|mega\.nz|we provide|we('ll| will) (send|provide|give)|b-?roll|content library|asset (pack|folder|library)|templates? (provided|below|included)|material(e)? fornit|materiale fornito|material proporcionado|vid[eé]os? fournies?|rushs?)"
FOOT_PUBLIC = r"(\bvods?\b|(twitch|kick|youtube|live) ?streams?|\bstreams?\b|livestreams?|(long[- ]form|youtube|full) (videos?|episodes?|content)|podcasts?|interviews?|(his|her|their) (content|videos?|channel|socials?|social media|accounts?|streams?)|social media accounts?|music videos?|\bmv\b|showcase|movie|film|trailer|episodes?|series)"
FOOT_OWN = r"(\bugc\b|film yourself|your own (content|video|face)|create your own|talking[- ]head|on camera|faceless|slideshows?|\btrend\b|\bmemes?\b|use the (campaign |official )?(sound|song|audio)|add the (sound|song)|with the (sound|song)|campaign sound|\bsong:|lip ?sync|dance)"
def footage(o, det):
    d = ((o.get("name") or "") + " " + (o.get("description") or "")).lower()
    types = {t["id"] for t in ((det.get("configuration") or {}).get("content") or {}).get("contentTypes", [])}
    cats = {c["id"] for c in o.get("categories") or []}
    if re.search(FOOT_GIVE, d):
        return "brand_provides"
    if re.search(FOOT_PUBLIC, d) and ("clipping" in types or re.search(r"\bclip", d)):
        return "public_source"
    if "sound-campaign" in cats or re.search(FOOT_OWN, d) or (types and types <= {"ugc-with-face", "ugc-faceless"}):
        return "own_content"
    return "unclear"


# ---------- AI classification (Gemini free tier); regex rules above are the fallback ----------
FOOT_LABEL = {
    "brand_provides": "✅|да, бренд даёт готовые видео/исходники",
    "public_source": "✅|да, нарезка из открытых видео/стримов автора, качаешь сам",
    "own_content": "❌|нет, свой контент (UGC/тренд/звук)",
    "unclear": "❔|не указано, смотри бриф",
}
AI_PROMPT = """You classify a short-form video clipping/UGC campaign for a Russian Telegram channel.
Return JSON only.
niches: 1-3 short Russian niche labels describing what the content is actually about (e.g. "Стримеры", "Гемблинг 18+", "AI", "Музыка", "Крипта", "Игры: Roblox", "Фитнес", "Кино и сериалы", "Приложения", "Бьюти", "Подкасты", "Спорт", "Финансы"). Judge by the real product/person, not only the brand's categories. Casino, betting, gambling streamers -> include "Гемблинг 18+".
footage: one of
  brand_provides = the brand gives the creator ready video files/footage/episodes/clips/assets/templates (drive, folder, "below", "provided", "supplied", "official videos", "content folder", raw videos ready);
  public_source = creator must cut clips from the person's public streams/VODs/YouTube/podcast/socials/film themselves, no files handed over;
  own_content = creator films or makes original content (UGC, talking head, skits, trends, slideshows, sound/song campaigns, screen recordings);
  unclear = the text does not say.
footage_note: up to 8 Russian words with the key detail (e.g. "50+ сырых видео в папке", "клипы со стримов Twitch", "снимаешь себя с приложением"); empty if unclear.
Campaign name: {name}
Brand categories: {cats}
Content types: {types}
Description: {desc}"""
AI_SCHEMA = {"type": "OBJECT", "properties": {
    "niches": {"type": "ARRAY", "items": {"type": "STRING"}},
    "footage": {"type": "STRING", "enum": list(FOOT_LABEL)},
    "footage_note": {"type": "STRING"}}, "required": ["niches", "footage", "footage_note"]}
_ai_off = False
_ai_model = None
def ai_model(key, force=False):
    """config ai_model; if Google 404s it (model retired), pick the newest *flash-lite*, else *flash* model."""
    global _ai_model
    if _ai_model and not force: return _ai_model
    if not force: _ai_model = CFG.get("ai_model", "gemini-2.5-flash-lite"); return _ai_model
    try:
        ms = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key, "pageSize": 1000}, timeout=30).json().get("models", [])
        names = [m["name"].split("/")[-1] for m in ms if "generateContent" in m.get("supportedGenerationMethods", [])]
        good = [n for n in names if n.startswith("gemini") and not re.search(r"preview|exp|tts|image|live|audio|thinking", n)]
        def rank(n): return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", n)[:1] or [0]]
        for pat in ("flash-lite", "flash"):
            c = sorted([n for n in good if pat in n and not (pat == "flash" and "lite" in n)], key=rank, reverse=True)
            if c: _ai_model = c[0]; break
        print("AI model ->", _ai_model, "| available:", ", ".join(names)[:600])
    except Exception as e:
        print("model list fail", str(e)[:200])
    return _ai_model
def ai_classify(o, det):
    global _ai_off
    key = os.environ.get("GEMINI_API_KEY")
    if not key or _ai_off: return None
    types = [t["name"] for t in ((det.get("configuration") or {}).get("content") or {}).get("contentTypes", [])]
    prompt = AI_PROMPT.format(name=o["name"], cats=", ".join(c["name"] for c in o.get("categories") or []),
                              types=", ".join(types) or "-", desc=(o.get("description") or "")[:3000])
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": AI_SCHEMA}}
    try:
        busy = 0
        for i in range(5):
            m = ai_model(key)
            if busy >= 2: m = CFG.get("ai_fallback_model", "gemini-2.5-flash")  # main model overloaded
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
            r = requests.post(url, params={"key": key}, json=body, timeout=40)
            if r.status_code == 404 and i == 0: ai_model(key, force=True); continue
            if r.status_code in (500, 502, 503, 504): busy += 1; time.sleep(4); continue
            if r.status_code == 429: time.sleep(20); continue
            if r.status_code >= 400: print("ai http", r.status_code, r.text[:300])
            r.raise_for_status()
            res = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            if res.get("footage") in FOOT_LABEL: return res
            return None
        _ai_off = True  # still rate-limited: rules for the rest of this run
    except Exception as e:
        print("ai fail", o["id"], str(e)[:200])
    return None

def caption(o, det):
    name = html.escape(o["name"].strip())
    ai = ai_classify(o, det)
    cats = list(dict.fromkeys(NICHE.get(c["id"], c["name"]) for c in o.get("categories") or []))
    if ai and ai.get("niches"): cats = list(dict.fromkeys(n.strip() for n in ai["niches"] if n.strip()))[:3]
    if not any("18+" in c for c in cats) and re.search(ADULT, (o["name"] + " " + (o.get("description") or "")).lower()):
        cats.append("Гемблинг 18+")
    types = [CTYPE.get(t["id"], t["name"]) for t in ((det.get("configuration") or {}).get("content") or {}).get("contentTypes", [])]
    budget = o.get("budgetCents") or 0
    spent = ((o.get("metrics") or {}).get("budgetSpentCents") or 0)
    pct = spent / budget * 100 if budget else 0
    L = [f"🆕 <b>{name}</b>", ""]
    if cats: L.append(f"🏷 <b>Ниша:</b> {html.escape(' · '.join(cats))}")
    if types: L.append(f"🎬 <b>Формат:</b> {html.escape(', '.join(types))}")
    fk = ai["footage"] if ai else footage(o, det)
    icon, foot = FOOT_LABEL[fk].split("|")
    if ai and ai.get("footage_note", "").strip() and fk != "unclear": foot += f" ({html.escape(ai['footage_note'].strip())})"
    L.append(f"{icon} <b>Готовый футаж:</b> {foot}")
    L += ["", f'👉 <a href="{link(o)}"><b>Открыть оффер</b></a>', ""]
    if o.get("payoutType") == "pool":
        L.append(f"🏆 <b>Пул {money(budget)}</b>, делится по просмотрам")
        L.append("   " + " ".join(emoji(p) for p in o.get("platforms", [])))
    else:
        L.append("<b>Ставки за 1K просмотров:</b>")
        for p in o.get("payouts") or []:
            s = f"{emoji(p['platform'])} {PLAT.get(p['platform'], p['platform'])} - <b>{money(p['rateCents'], True)}</b>"
            if p.get("maxPayoutCents"): s += f" (до {money(p['maxPayoutCents'])} за пост)"
            L.append(s)
    L.append(f"💵 <b>Бюджет:</b> {money(budget)}" + (f", потрачено {pct:.0f}%" if spent else ""))
    if o.get("geoPriced"): L.append("🌍 Ставка зависит от гео аудитории")
    if o.get("requiresApplication"): L.append("📝 По заявке")
    org = (det.get("organization") or {}).get("name") or o.get("organizationName")
    if org:
        st = ORG.get(o.get("organizationId")) or {}
        bits = ["☑️ с галочкой CR" if o.get("organizationVerified") or (det.get("organization") or {}).get("verified") else "без галочки CR"]
        if st.get("n", 0) > 1: bits.append(f"{st['n']} активных кампаний")
        bits.append(f"уже потратил на клипперов {money(st['paid'])}" if st.get("paid") else "клипперам пока ничего не платил")
        L.append(f"🏢 <b>Рекламодатель:</b> {html.escape(org)} ({', '.join(bits)})")
    sig = CFG.get("signature") or {}
    tail = f'\n\n[ {html.escape(sig.get("prefix", "By"))} <a href="{sig["url"]}">{html.escape(sig["text"])}</a> ]' if sig.get("url") else ""
    s = "\n".join(L)
    lim = 1024 - len(tail)  # signature is never cut off; drop optional lines, never cut HTML mid-tag
    while len(s) > lim and len(L) > 8:
        L.pop(); s = "\n".join(L)
    return s + tail

def link(o):
    base = f"https://contentrewards.com/c/campaigns/{o['id']}"
    tpl = CFG.get("link_template")  # e.g. "https://contentrewards.com/c/campaigns/{id}?ref=CODE"
    return tpl.format(id=o["id"]) if tpl else base

def banner(o):
    if not o.get("banner"): return None
    try:
        from PIL import Image
        r = requests.get(CDN + o["banner"], headers=HDR, timeout=30); r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        b = io.BytesIO(); im.save(b, "JPEG", quality=92); b.name = "banner.jpg"; b.seek(0)
        return b
    except Exception as e:
        print("banner fail", o["id"], e); return None

async def post(items, seen):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    async with TelegramClient(StringSession(os.environ["TG_SESSION"]), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]) as cl:
        ch = await cl.get_entity(CFG["channel"])
        for o, det in items:
            cap = caption(o, det); img = banner(o)
            if img: await cl.send_file(ch, img, caption=cap, parse_mode="html")
            else: await cl.send_message(ch, cap, parse_mode="html", link_preview=False)
            seen.add(o["id"]); json.dump(sorted(seen), open(SEEN, "w"))
            print("posted", o["name"]); await asyncio.sleep(3)

def ai_test():
    """python main.py --ai-test : compare AI and rules with hand labels in tests/ai_labels.json (no posting)."""
    data = json.load(open(os.path.join(HERE, "tests", "ai_labels.json"), encoding="utf-8"))
    rev = {v: k for k, v in FOOT_LABEL.items()}
    ai_ok = rule_ok = n_ai = 0
    for d in data:
        o = d["offer"]; ai = ai_classify(o, {}); rule = rev[footage(o, {})]
        rule_ok += rule in d["accept"]
        if ai: n_ai += 1; ai_ok += ai["footage"] in d["accept"]
        print(f"{o['name'][:45]:45} | ждём {'/'.join(d['accept']):28} | AI {(ai or {}).get('footage','-'):15} {'OK ' if ai and ai['footage'] in d['accept'] else 'ERR'} | правила {rule:15} | ниши AI: {', '.join((ai or {}).get('niches', []))} | {(ai or {}).get('footage_note','')}")
        time.sleep(4)  # stay under free-tier per-minute limit
    print(f"\nAI ответил на {n_ai}/{len(data)}, футаж верно: {ai_ok}/{n_ai}; правила: {rule_ok}/{len(data)}")

ORG = {}
def org_stats(camps):
    """Advertiser track record from Content Rewards public data (active campaigns only; CR has no public rating)."""
    for o in camps:
        a = ORG.setdefault(o.get("organizationId"), {"n": 0, "paid": 0})
        a["n"] += 1; a["paid"] += ((o.get("metrics") or {}).get("budgetSpentCents") or 0)  # paidOutCents is always 0 publicly

def main():
    if "--ai-test" in sys.argv: return ai_test()
    dry = "--dry" in sys.argv
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else None
    allc = newest(); org_stats(allc)
    camps = [o for o in allc if o.get("status") == "active" and not o.get("private")]
    if "--backfill" in sys.argv:  # test: post the N newest offers again, state untouched
        n = int(sys.argv[sys.argv.index("--backfill") + 1])
        pool = camps
        if "--all-platforms" in sys.argv:  # only offers paying on X, TikTok, Instagram and YouTube
            pool = [o for o in camps if {"x", "tiktok", "instagram", "youtube"} <= set(o.get("platforms") or [])]
        items = [(o, get(f"{API}/{o['id']}").get("data") or {}) for o in pool[:n]][::-1]
        if dry:
            for o, d in items: print(caption(o, d), "\n" + "-" * 40)
        else: asyncio.run(post(items, set(seen or ())))
        return
    if seen is None:  # first run: remember everything, post only the newest N for a test
        n = int(CFG.get("first_run_post", 0)); seen = {o["id"] for o in camps[n:]}
    new = [o for o in camps if o["id"] not in seen][::-1][: int(CFG.get("max_per_run", 15))]
    items = [(o, get(f"{API}/{o['id']}").get("data") or {}) for o in new]
    if dry:
        for o, d in items: print(caption(o, d), "\n" + "-" * 40)
    elif items:
        asyncio.run(post(items, seen))
    seen |= {o["id"] for o, _ in items}
    if not dry: json.dump(sorted(seen), open(SEEN, "w"))
    print(f"new: {len(items)}")

if __name__ == "__main__":
    main()
