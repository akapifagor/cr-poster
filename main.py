"""Content Rewards -> Telegram channel poster (userbot, custom emoji).

python main.py --loop    GitHub Actions mode: poll CR every poll_seconds for loop_minutes, post new offers right away,
                         commit seen.json after every change (see .github/workflows/post.yml)
python main.py           one pass: post new offers and exit
python main.py --dry     print captions of new offers, post nothing, state untouched
python main.py --backfill N [--all-platforms]   repost the N newest offers (test), state untouched
python main.py --ai-test compare AI and rules with tests/ai_labels.json (no posting)
New offers = active public campaigns whose id is not in seen.json.
"""
from datetime import datetime, timedelta, timezone
import io, json, os, re, sys, time, asyncio, html, subprocess, traceback
import requests

API = "https://contentrewards.com/api/campaign/campaigns"
HDR = {"x-cr-app": "creators", "user-agent": "Mozilla/5.0"}
CDN = "https://crusercontent.com/"
HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "seen.json")
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
CAMP_RE = re.compile(r"contentrewards\.com/c/campaigns/([0-9a-f-]{36})")

NICHE = {  # CR category id -> RU label (unknown ids fall back to CR's English name)
 "artificial-intelligence": "AI", "ai-tools": "AI-сервисы", "ai-video": "AI-видео", "technology": "Технологии",
 "software": "Софт", "saas": "SaaS", "developer-tools": "Инструменты для разработчиков", "productivity-tools": "Продуктивность",
 "productivity": "Продуктивность", "gadgets": "Гаджеты", "app": "Приложения", "mobile-app": "Приложения",
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
# niche labels the AI may use (one vocabulary -> consistent tags across posts); "Игры: <title>" is allowed for one specific game
NICHES = ["AI", "Приложения", "Технологии", "Игры", "Киберспорт", "Стримеры", "Блогеры", "Знаменитости", "Юмор", "Развлечения",
          "Шоу и интервью", "Музыка", "Подкасты", "Кино и сериалы", "Аниме", "Спорт", "Футбол", "Фитнес", "Здоровье", "Бьюти",
          "Мода", "Лайфстайл", "Еда и напитки", "Путешествия", "Авто", "Бизнес", "Финансы", "Крипта", "Трейдинг", "Недвижимость",
          "E-commerce", "Маркетинг", "Образование", "Саморазвитие", "Отношения", "Семья", "Питомцы", "Политика", "Религия",
          "Гемблинг 18+"]
GAME_NICHE = re.compile(r"Игры: [A-Za-z0-9À-ÿ][A-Za-z0-9À-ÿ .:'&+!-]{1,29}")
# gambling markers; a match right after a negation ("no casino, gambling or memecoin pages") does not count
ADULT = (r"\b(casinos?|gambl\w*|slot machines?|online slots|slots? (?:streams?|games?|bonus|spins?)|roulette|bett?ing|"
         r"sportsbooks?|sweepstakes?|stake\.(?:com|us)|roobet|shuffle\.com|metawin|rollbit|bc\.game|gamdom|duelbits|rainbet|"
         r"winna|poker|blackjack|bookmakers?|igaming|1win|1xbet|parimatch)\b")
NOT_ADULT = r"\b(chat ?roulette)\b"
CTYPE = {"clipping": "Клиппинг", "youtube-long-form": "Длинные видео YouTube", "ugc-with-face": "UGC с лицом", "ugc-faceless": "UGC без лица",
         "editing": "Монтаж", "slideshow": "Слайдшоу", "slideshows": "Слайдшоу", "meme": "Мемы", "repost": "Репосты",
         "reposting": "Репосты", "sound": "Под звук/трек", "logo": "С логотипом бренда"}
ORDER = ["x", "tiktok", "instagram", "youtube", "facebook", "snapchat", "threads"]
PLAT = {"x": "X", "tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube Shorts", "facebook": "Facebook",
        "snapchat": "Snapchat", "threads": "Threads"}
PLAT_FALLBACK = {"x": "𝕏", "tiktok": "🎵", "instagram": "📸", "youtube": "▶️", "facebook": "📘", "snapchat": "👻", "threads": "🧵"}

def brief(o, det):
    """all text a brand wrote: name, org, description, guidelines"""
    g = ((det.get("configuration") or {}).get("content") or {}).get("guidelines") or ""
    org = (det.get("organization") or {}).get("name") or o.get("organizationName") or ""
    return f"{o.get('name') or ''} {org} {o.get('description') or ''} {g if isinstance(g, str) else json.dumps(g)}"

def adult(text):
    t = re.sub(NOT_ADULT, " ", text.lower())
    for m in re.finditer(ADULT, t):
        before = re.split(r"[.!?\n]", t[max(0, m.start() - 40):m.start()])[-1]
        if not re.search(r"\b(no|not|never|without|avoid|nor|don'?t)\b", before): return True
    return False

def get(url, **kw):
    """JSON GET with retries on network errors / 5xx / 429. None for 403/404 (campaign gone or private)."""
    err = None
    for i in range(4):
        try:
            r = requests.get(url, headers=HDR, timeout=30, **kw)
            if r.status_code == 200: return r.json()
            if r.status_code in (403, 404): return None
            err = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            err = repr(e)[:200]
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"GET {url} failed: {err}")

def detail(cid):
    """campaign detail; None if CR no longer serves it"""
    d = get(f"{API}/{cid}")
    return None if d is None else (d.get("data") or {})

def eligible(o):
    return o.get("status") == "active" and not o.get("private")

def newest(seen=None, pages=20):
    """discover list, newest first. With `seen`: stop after the first page whose eligible offers are all known (cheap poll)."""
    out, cur = [], None
    for _ in range(pages):
        q = {"limit": 100, "sortBy": "newest"}
        if cur: q["cursor"] = cur
        d = get(API + "/discover", params=q)
        if d is None: raise RuntimeError("discover endpoint answered 403/404")
        page = d.get("data") or []
        out += page
        cur = (d.get("pagination") or {}).get("nextCursor")
        if not cur or not page: break
        if seen is not None and all(o.get("id") in seen for o in page if eligible(o)): break
    return out

def money(c, rate=False):
    v = c / 100
    return f"${v:,.2f}" if rate or v != int(v) and v < 100 else f"${v:,.0f}"

def kviews(n):
    """views count, 3 significant digits: 670, 1.33K, 33.3K, 1.2M"""
    if n < 1000: return str(int(round(n, -1) if n >= 100 else round(n)))
    if n >= 999_500: return f"{n / 1e6:.3g}M"
    return f"{n / 1000:.3g}K"

def plural(n, one, few, many):
    return one if n % 10 == 1 and n % 100 != 11 else few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many

def emoji(p):
    fb = PLAT_FALLBACK.get(p, "•")
    eid = (CFG.get("platform_emoji") or {}).get(p)
    return f'<tg-emoji emoji-id="{eid}">⭐</tg-emoji>' if eid else fb  # inner text must be a real emoji

def flag(cc):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc.upper())

def geo_label(t):
    """country flags for a geo tier (brand labels like "spanish" or "tier 1" are vague); label for long lists"""
    cs = [c for c in t.get("countries") or [] if isinstance(c, str) and re.fullmatch(r"[A-Za-z]{2}", c)]
    if cs and len(cs) <= 10: return "".join(flag(c) for c in cs)
    lab = html.escape((t.get("label") or "").strip())
    return f"{lab} ({len(cs)} {plural(len(cs), 'страна', 'страны', 'стран')})" if lab and cs else lab or "гео"

# Footage detection (heuristic on the offer description; EN + common IT/ES/FR/PT/DE words)
FOOT_GIVE = r"(source footage|our footage|(from|of) (our|the reference|the provided|the approved) (videos?|clips?|footage|content|episodes?)|(footage|videos?|clips?|episodes?|assets?|content|materials?) (is |are )?(provided|supplied|attached|included|below|linked|in the (drive|folder|brief|link))|(provided|supplied|official|attached) (footage|videos?|clips?|episodes?|assets?|content|materials?|b-?roll)|(use|clip|edit) (the|our) \d* ?(official )?(videos?|clips?|footage|episodes?)( below)?|raw footage|google drive|drive\.google|dropbox|mega\.nz|we provide|we('ll| will) (send|provide|give)|b-?roll|content library|asset (pack|folder|library)|templates? (provided|below|included)|material(e)? fornit|materiale fornito|material proporcionado|vid[eé]os? fournies?|rushs?)"
FOOT_PUBLIC = r"(\bvods?\b|(twitch|kick|youtube|live) ?streams?|\bstreams?\b|livestreams?|(long[- ]form|youtube|full) (videos?|episodes?|content)|podcasts?|interviews?|(his|her|their) (content|videos?|channel|socials?|social media|accounts?|streams?)|social media accounts?|music videos?|\bmv\b|showcase|movie|film|trailer|episodes?|series)"
FOOT_OWN = r"(\bugc\b|film yourself|your own (content|video|face)|create your own|talking[- ]head|on camera|faceless|slideshows?|\btrend\b|\bmemes?\b|use the (campaign |official )?(sound|song|audio)|add the (sound|song)|with the (sound|song)|campaign sound|\bsong:|lip ?sync|dance)"
def footage(o, det):
    d = brief(o, det).lower()
    types = {t["id"] for t in ((det.get("configuration") or {}).get("content") or {}).get("contentTypes", [])}
    cats = {c["id"] for c in o.get("categories") or []}
    if re.search(FOOT_GIVE, d):
        return "brand_provides"
    if re.search(FOOT_PUBLIC, d) and ("clipping" in types or re.search(r"\bclip", d)):
        return "public_source"
    if "sound-campaign" in cats or re.search(FOOT_OWN, d) or (types and types <= {"ugc-with-face", "ugc-faceless", "slideshows", "sound"}):
        return "own_content"
    if types == {"clipping"} or (not types and re.search(r"\bclip(s|ping|per)?\b", d)):
        return "public_source"  # clipping = cutting the creator's own public content
    return "unclear"


# ---------- AI classification (Gemini free tier); regex rules above are the fallback ----------
FOOT_LABEL = {
    "brand_provides": "✅|да, бренд даёт готовые видео/исходники",
    "public_source": "✅|да, нарезка из открытых видео/стримов, качаешь сам",
    "own_content": "❌|нет, свой контент (UGC/тренд/звук)",
    "unclear": "❔|не указано, смотри бриф",
}
FORMATS = list(dict.fromkeys(CTYPE.values()))
AI_PROMPT = """You classify a short-form video clipping/UGC campaign for a Russian Telegram channel. Return JSON only.
niches: 1-3 values, most important first. Judge by what the campaign actually promotes (the product, app, person, song, film or show), NOT by the edit styles or footage used: a song pushed through movie, fashion, car or anime edits is "Музыка" only; clips of a streamer are "Стримеры"; clips of a podcast are "Подкасты".
  "Кино и сериалы" only when the promoted thing is a film, TV/streaming series, docuseries or film trailer; never for YouTube shows, podcasts, game trailers or edits that merely reuse movie scenes.
  "Подкасты" only when the source really is a podcast. "Шоу и интервью" for YouTube shows, challenge shows and interviews that are not podcasts.
  "Гемблинг 18+" only when the campaign promotes a casino, betting, sweepstakes, poker or a gambling streamer; never because the brief forbids gambling content.
game: when the campaign is about one specific video game, its official title in Latin letters as the publisher writes it (e.g. "Roblox", "GTA 6", "Call of Duty", "Football Manager 27") and "Игры" among niches; otherwise "".
footage: one of
  brand_provides = the brand gives the creator ready video files/footage/episodes/clips/assets/templates (drive, folder, "below", "provided", "supplied", "official videos", "content folder", raw videos ready);
  public_source = creator must cut clips from the person's public streams/VODs/YouTube/podcast/socials/film themselves, no files handed over;
  own_content = creator films or makes original content (UGC, talking head, skits, trends, slideshows, sound/song campaigns, screen recordings, recording own gameplay);
  unclear = the text does not say.
  Edits made from movie/TV/anime/film scenes or other public footage (e.g. "movie + TV edits") are public_source.
  "Clipping" campaigns about a streamer/podcaster/creator with no files mentioned are public_source.
footage_note: the key detail about the source material in 3-8 words of plain, correctly spelled Russian, starting with a lowercase letter, no final period (e.g. "50+ сырых видео в папке", "клипы со стримов Twitch", "снимаешь себя с приложением"). Use the words "видео", "исходники", "клипы", "запись экрана"; never write "футаж" or any other transliteration of "footage". Keep names of brands, platforms and people as written (Twitch, YouTube, Google Drive). "" if footage is unclear.
format: only if "Content types" below is "-": 1-3 values for what the creator makes; otherwise [].
Campaign name: {name}
Advertiser: {org}
Brand categories: {cats}
Content types: {types}
Description and guidelines: {desc}"""
AI_SCHEMA = {"type": "OBJECT", "properties": {  # enums: Gemini can only answer with valid labels
    "niches": {"type": "ARRAY", "items": {"type": "STRING", "enum": NICHES}, "maxItems": 3},
    "game": {"type": "STRING"},
    "footage": {"type": "STRING", "enum": list(FOOT_LABEL)},
    "footage_note": {"type": "STRING"},
    "format": {"type": "ARRAY", "items": {"type": "STRING", "enum": FORMATS}, "maxItems": 3}},
    "required": ["niches", "game", "footage", "footage_note", "format"],
    "propertyOrdering": ["niches", "game", "footage", "footage_note", "format"]}
_ai_off = {}  # model -> time it may be tried again (its daily free quota is used up / it is gone)
_ai_model = None
def clean_niches(ns):
    """keep only labels from the vocabulary (plus "Игры: <title>"), max 3"""
    ns = [n.strip() for n in ns or [] if isinstance(n, str)]
    return list(dict.fromkeys(n for n in ns if n in NICHES or GAME_NICHE.fullmatch(n)))[:3]
def clean_note(s):
    """footage note as shown in the post: one style, no mangled words, no English-only answers"""
    s = re.sub(r"\s+", " ", str(s or "")).strip(" .;:,\"'«»()[]")
    s = re.sub(r"(?i)\bф[ую]т[а-яё]*ж[а-яё]*", "видео", s)  # "футаж", "футюдж", "футуэдж": the model mangles "footage"
    if not re.search(r"[а-яё]", s, re.I): return ""  # English or junk -> no note rather than a wrong one
    if len(s) > 70: s = s[:70].rsplit(" ", 1)[0]
    if re.match(r"[А-ЯЁ][а-яё]+(\s|$)", s): s = s[0].lower() + s[1:]  # "Клипы со стримов" -> "клипы со стримов"; keeps "YouTube", "ТНТ"
    return s
def ai_postprocess(res):
    """validated AI answer or None"""
    if not isinstance(res, dict) or res.get("footage") not in FOOT_LABEL: return None
    ns = clean_niches(res.get("niches"))
    game = re.sub(r"\s+", " ", str(res.get("game") or "")).strip(" \"'«»")
    if game and "Игры" in ns and GAME_NICHE.fullmatch(f"Игры: {game}"): ns[ns.index("Игры")] = f"Игры: {game}"
    fmt = res.get("format") if isinstance(res.get("format"), list) else []
    return {"niches": ns, "footage": res["footage"], "footage_note": clean_note(res.get("footage_note")) if res["footage"] != "unclear" else "",
            "format": [f for f in dict.fromkeys(fmt) if f in FORMATS][:3], "raw_note": str(res.get("footage_note") or "")}
def ai_model(key, force=False):
    """AI_MODEL env / config ai_model; if Google 404s it (model retired), pick the newest *flash-lite*, else *flash* model."""
    global _ai_model
    if _ai_model and not force: return _ai_model
    if not force: _ai_model = os.environ.get("AI_MODEL") or CFG.get("ai_model", "gemini-2.5-flash-lite"); return _ai_model
    try:
        ms = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 1000}, headers={"x-goog-api-key": key}, timeout=30).json().get("models", [])
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
def ai_models(key):
    """main model, then the fallback; models whose daily quota is used up are skipped until it resets"""
    chain = [ai_model(key), os.environ.get("AI_FALLBACK_MODEL") or CFG.get("ai_fallback_model")]
    return [m for m in dict.fromkeys(chain) if m and time.time() >= _ai_off.get(m, 0)]
def ai_classify(o, det):
    key = os.environ.get("GEMINI_API_KEY")
    if not key: return None
    types = [t["name"] for t in ((det.get("configuration") or {}).get("content") or {}).get("contentTypes", [])]
    g = ((det.get("configuration") or {}).get("content") or {}).get("guidelines") or ""
    prompt = AI_PROMPT.format(name=o["name"], org=(det.get("organization") or {}).get("name") or o.get("organizationName") or "-",
                              cats=", ".join(c["name"] for c in o.get("categories") or []), types=", ".join(types) or "-",
                              desc=((o.get("description") or "") + "\n" + (g if isinstance(g, str) else json.dumps(g, ensure_ascii=False)))[:4000])
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "seed": 7, "responseMimeType": "application/json", "responseSchema": AI_SCHEMA}}
    try:
        busy = 0
        for i in range(6):
            ms = ai_models(key)
            if not ms: print("ai: free quota of all models used up, rules for now"); return None
            m = ms[-1] if busy >= 2 else ms[0]  # main model overloaded -> fallback
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
            try: r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=40)  # key in a header: never part of a URL in error logs
            except (requests.Timeout, requests.ConnectionError) as e:  # slow/unreachable model: retry, then the fallback model
                print("ai", m, type(e).__name__); busy += 1; continue
            if r.status_code == 404:
                if m == _ai_model and i == 0: ai_model(key, force=True)
                else: _ai_off[m] = time.time() + 86400
                continue
            if r.status_code in (500, 502, 503, 504): busy += 1; time.sleep(4); continue
            if r.status_code == 429:
                t = r.text
                if "PerDay" in t or "per day" in t.lower():  # daily free quota of this model: next model, this one again in an hour
                    print(f"ai: daily free quota of {m} used up, switching model"); _ai_off[m] = time.time() + 3600; continue
                m2 = re.search(r'"retryDelay":\s*"(\d+)', t)
                print("ai 429, wait", m2.group(1) if m2 else 20, "s")
                time.sleep(min(int(m2.group(1)) + 1 if m2 else 20, 65)); continue
            if r.status_code >= 400: print("ai http", m, r.status_code, r.text[:300])
            r.raise_for_status()
            res = ai_postprocess(json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"]))
            if res: res["model"] = m
            return res
        print("ai: gave up on", o.get("name", "")[:40], "-> rules")  # this offer only
    except Exception as e:
        print("ai fail", o["id"], str(e)[:200])
    return None

def visible_len(s):
    """caption length as Telegram counts it: text without HTML tags, UTF-16 units"""
    from telethon.extensions import html as tg_html
    return len(tg_html.parse(s)[0].encode("utf-16-le")) // 2

def caption(o, det):
    det = det or {}
    conf = det.get("configuration") or {}
    name = html.escape(re.sub(r"(?i)\b([a-z0-9-]+)\.(com|io|app|net|org|gg|ai|co|xyz|tv|fun)\b", "\\1.\u2060\\2", o["name"].strip()))  # stop Telegram auto-linking "Oceans.com" in titles
    ai = ai_classify(o, det)
    cats = list(dict.fromkeys(NICHE.get(c["id"], c["name"]) for c in o.get("categories") or []))
    if ai and ai.get("niches"): cats = ai["niches"]
    if not any("18+" in c for c in cats) and adult(brief(o, det)):
        cats.append("Гемблинг 18+")
    types = [CTYPE.get(t["id"], t["name"]) for t in (conf.get("content") or {}).get("contentTypes", [])]
    budget = o.get("budgetCents") or 0
    spent = ((o.get("metrics") or {}).get("budgetSpentCents") or 0)
    pct = spent / budget * 100 if budget else 0
    if not types and ai and ai.get("format"): types = ai["format"]
    L = [f"<b>{name}</b>", ""]
    if cats: L.append(f"🏷 <b>Ниша:</b> {html.escape(' · '.join(cats))}")
    if types: L.append(f"🎬 <b>Формат:</b> {html.escape(', '.join(types[:3]))}")
    fk = ai["footage"] if ai else footage(o, det)
    icon, foot = FOOT_LABEL[fk].split("|")
    note = html.escape(ai["footage_note"]) if ai and ai.get("footage_note") else ""
    L.append(f"{icon} <b>Готовый футаж:</b> {foot}" + (f" ({note})" if note else ""))
    i_foot = len(L) - 1
    L += ["", f'👉 <a href="{link(o)}"><b>Открыть оффер</b></a>', ""]
    def pl_sorted(ps): return sorted(ps, key=lambda p: ORDER.index(p) if p in ORDER else 99)
    geo_shown = False
    if o.get("payoutType") == "pool":
        L.append(f"🏆 <b>Пул {money(budget)}</b>, делится по просмотрам")
        L.append("Площадки: " + " ".join(emoji(p) for p in pl_sorted(o.get("platforms", []))))
        cv, mv = conf.get("minCreatorViews") or 0, conf.get("minClipViews") or 0
        cond = ([f"от {kviews(cv)} просмотров суммарно"] if cv > 1 else []) + ([f"клип засчитывается от {kviews(mv)} просмотров"] if mv > 1 else [])
        if cond: L.append("👀 <b>Чтобы попасть в пул:</b> " + ", ".join(cond))
        L.append("⏳ Выплата после закрытия пула")
    elif any(p.get("payoutType") == "retainer" for p in o.get("payouts") or []) or o.get("payoutType") == "retainer":
        rp = [p for p in o.get("payouts") or [] if p.get("payoutType") == "retainer"]
        r0 = rp[0] if rp else {}
        amt, n = r0.get("amountCents") or 0, r0.get("deliverablesTotal") or 0
        cyc = {"monthly": "в месяц", "weekly": "в неделю"}.get(r0.get("cycleLength"), "")
        L.append(f"💼 <b>Ретейнер:</b> {money(amt)} {cyc}".rstrip() + (f" за {n} роликов (~{money(amt / n)} за ролик)" if amt and n else ""))
        L.append("Площадки: " + " ".join(emoji(p) for p in pl_sorted({p["platform"] for p in rp} or set(o.get("platforms", [])))))
    elif o.get("payoutType") == "perPost" or any(p.get("payoutType") == "perPost" for p in o.get("payouts") or []):
        pp = sorted([p for p in o.get("payouts") or [] if p.get("payoutType") == "perPost"], key=lambda p: ORDER.index(p["platform"]) if p["platform"] in ORDER else 99)
        amts = {p.get("amountCents") or 0 for p in pp}
        if len(amts) == 1:
            L.append(f"💲 <b>Фикс за пост:</b> {money(next(iter(amts)))} (не зависит от просмотров)")
            L.append("Площадки: " + " ".join(emoji(p["platform"]) for p in pp))
        else:
            L.append("💲 <b>Фикс за пост</b> (не зависит от просмотров):")
            for p in pp: L.append(f"{emoji(p['platform'])} {PLAT.get(p['platform'], p['platform'])} - <b>{money(p.get('amountCents') or 0)}</b>")
    elif o.get("payoutType") == "cpm" or any("rateCents" in p for p in o.get("payouts") or []):
        # geo pricing: CR applies geoRates whenever they exist for a platform (the geoPriced flag is not reliable);
        # the rate for "other countries" is geoRates.restOfWorld, listing rateCents is 0 for such platforms
        geo = conf.get("geoRates") or {}
        tiers = geo.get("tiers") or []
        row = {x.get("platform"): x.get("rate") or 0 for x in geo.get("restOfWorld") or []}
        def prate(p):  # -> (flat rate or None, [(rate, labels)] paid tiers best first, rest-of-world rate, unpaid labels)
            pt = [t for t in tiers if t.get("platform") == p.get("platform")]
            if not pt: return (p.get("rateCents") or row.get(p.get("platform")) or 0), [], 0, []
            by = {}
            for t in pt:
                if t.get("rate"): by.setdefault(t["rate"], []).append(geo_label(t))
            return None, sorted(by.items(), key=lambda x: -x[0]), row.get(p["platform"], p.get("rateCents") or 0), [geo_label(t) for t in pt if not t.get("rate")]
        def top(p):
            flat, paid, rest, _ = prate(p)
            return flat if flat is not None else max([rest] + [r for r, _ in paid])
        L.append("<b>Ставки за 1K просмотров:</b>")
        pays = sorted([p for p in o.get("payouts") or [] if top(p)], key=lambda p: ORDER.index(p["platform"]) if p["platform"] in ORDER else 99)
        def rng(p):  # max payout per post + views a post needs before it pays (CR "Min payout" / rate)
            lo, hi, r = p.get("minPayoutCents") or 0, p.get("maxPayoutCents") or 0, top(p)
            bits = [f"до {money(hi)}"] if hi else []
            if lo and r: bits.append(f"оплата от {kviews(lo / r * 1000)} просмотров")
            return ", ".join(bits)
        def join_labels(labs): return ("" if all(not re.search(r"[\w(]", x) for x in labs) else ", ").join(labs)
        rngs = {rng(p) for p in pays}
        same = len(rngs) == 1  # one rule for all platforms -> its own line, rate lines stay short
        for p in pays:
            flat, paid, rest, unpaid = prate(p)
            if flat is not None:
                body = f"<b>{money(flat, True)}</b>"
            else:
                geo_shown = True
                parts = [f"<b>{money(r, True)}</b> {join_labels(labs)}" for r, labs in paid]
                if rest: parts.append(f"<b>{money(rest, True)}</b>" + (" остальной мир" if paid else ""))
                else: parts.append("остальной мир не оплачивается")
                body = ", ".join(parts) + (f", кроме {join_labels(unpaid)}" if rest and unpaid else "")
            s = f"{emoji(p['platform'])} {PLAT.get(p['platform'], p['platform'])} - {body}"
            if not same and rng(p): s += f" ({rng(p)})"
            L.append(s)
        if not pays: L.append("ставки в оффере (зависят от гео)" if o.get("geoPriced") else "ставки в оффере")
        if same and pays and next(iter(rngs)): L.append(f"📌 <b>За пост:</b> {next(iter(rngs))}")
    else:  # unknown future payout type: post anyway, point to the offer
        print("WARN unknown payoutType", o.get("payoutType"), o.get("id"))
        L.append(f"💰 <b>Оплата:</b> {html.escape(str(o.get('payoutType') or 'не указан'))}, условия в оффере")
    ms = conf.get("maxSubmissionsPerUser")
    if isinstance(ms, int) and 0 < ms <= 20: L.append(f"🔢 <b>Лимит:</b> {ms} {plural(ms, 'пост', 'поста', 'постов')} на креатора")
    L.append("")  # budget/advertiser block separated from rates
    pb = [p for p in o.get("payouts") or [] if p.get("budgetCents")]  # some offers split the budget per platform
    pbs = f" ({', '.join(PLAT.get(p['platform'], p['platform']) + ' ' + money(p['budgetCents']) for p in sorted(pb, key=lambda p: ORDER.index(p['platform']) if p['platform'] in ORDER else 99))})" if pb and len({p['budgetCents'] for p in pb}) > 1 else ""
    L.append(f"💵 <b>Бюджет:</b> {money(budget)}{pbs}" + ((", потрачено <1%" if pct < 1 else f", потрачено {pct:.0f}%") if spent else ""))
    if o.get("geoPriced") and not geo_shown: L.append("🌍 Ставка зависит от гео аудитории")
    if o.get("requiresApplication"): L.append("📝 По заявке")
    org = (det.get("organization") or {}).get("name") or o.get("organizationName")
    i_org = None
    if org:
        st = ORG.get(o.get("organizationId")) or {}
        bits = ["с галочкой CR" if o.get("organizationVerified") or (det.get("organization") or {}).get("verified") else "без галочки CR"]
        if st.get("n", 0) > 1: bits.append(f"{st['n']} {plural(st['n'], 'активная кампания', 'активные кампании', 'активных кампаний')}")
        bits.append(f"клипперам начислено ${st['paid'] / 100:,.0f}" if st.get("paid", 0) >= 100 else "пока без начислений")
        L.append(f"🏢 <b>Рекламодатель:</b> {html.escape(org)} ({', '.join(bits)})")
        i_org = len(L) - 1
    sig = CFG.get("signature") or {}
    tail = f'\n\n[ {html.escape(sig.get("prefix", "By"))} <a href="{sig["url"]}">{html.escape(sig["text"])}</a> ]' if sig.get("url") else ""
    lim = 1024  # Telegram media caption limit (visible text); real captions are ~400-650, this is a safety net
    def fits(): return visible_len("\n".join(L) + tail) <= lim
    if not fits() and note: L[i_foot] = f"{icon} <b>Готовый футаж:</b> {foot}"  # 1) drop the AI footage note
    if not fits() and i_org is not None: L[i_org] = f"🏢 <b>Рекламодатель:</b> {html.escape(org)}"  # 2) advertiser stats
    while not fits() and len(L) > 8: L.pop()  # 3) last resort: drop trailing lines whole, never cut HTML mid-tag
    return "\n".join(L) + tail

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

ORG = {}
def org_stats(camps):
    """Advertiser track record from Content Rewards public data (active campaigns only; CR has no public rating)."""
    ORG.clear()
    for o in camps:
        if not eligible(o): continue
        a = ORG.setdefault(o.get("organizationId"), {"n": 0, "paid": 0})
        a["n"] += 1; a["paid"] += ((o.get("metrics") or {}).get("budgetSpentCents") or 0)  # earned by clippers; paidOutCents is always 0 publicly

def parse_ts(v):
    if not v: return None
    v = str(v)
    try: return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError: pass
    m = re.match(r"\w+ (\d{4}-\d\d-\d\d) (\d+:\d\d [AP]M) \w+ \(UTC([+-]\d\d):(\d\d)\)", v)
    if not m: return None
    tz = timezone(timedelta(hours=int(m[3]), minutes=int(m[4]) * (1 if m[3][0] == "+" else -1)))
    return datetime.strptime(f"{m[1]} {m[2]}", "%Y-%m-%d %I:%M %p").replace(tzinfo=tz)

# ---------- state ----------
def load_seen():
    return set(json.load(open(SEEN))) if os.path.exists(SEEN) else None

def save_seen(seen):
    tmp = SEEN + ".tmp"
    with open(tmp, "w") as f: json.dump(sorted(seen), f)
    os.replace(tmp, SEEN)

def git_sync(seen):
    """GitHub Actions only: commit seen.json and push. Merges with the remote copy first, so a concurrent push never loses ids."""
    if os.environ.get("GITHUB_ACTIONS") != "true": return True
    br = os.environ.get("GITHUB_REF_NAME") or "main"
    def git(*a): return subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True, check=True, timeout=120).stdout
    for i in range(4):
        try:
            git("fetch", "-q", "origin", br)
            try: seen |= set(json.loads(git("show", "FETCH_HEAD:seen.json")))
            except (subprocess.CalledProcessError, ValueError): pass
            git("reset", "-q", "--hard", "FETCH_HEAD")
            save_seen(seen)
            if not git("status", "--porcelain", "seen.json").strip(): return True
            git("-c", "user.name=bot", "-c", "user.email=bot@users.noreply.github.com", "commit", "-q", "-m", "seen", "seen.json")
            git("push", "-q", "origin", f"HEAD:{br}")
            return True
        except (subprocess.SubprocessError, OSError) as e:
            print("git sync retry", i, (getattr(e, "stderr", "") or repr(e)).strip()[:300]); time.sleep(3 + 5 * i)
    print("WARN git sync failed, will retry next cycle")
    return False

def select(camps, seen):
    """new offers to post, oldest first. Never-seen offers that are stale (listed > max_age_hours ago: deeper pages,
    old offers resurfacing) or nearly spent are marked seen silently."""
    act = [o for o in camps if eligible(o)]
    cut = datetime.now(timezone.utc) - timedelta(hours=float(CFG.get("max_age_hours", 48)))
    def fresh(o):
        t = parse_ts(o.get("listedAt") or o.get("launchDate") or o.get("createdAt"))  # listedAt = went public; createdAt can be a days-old draft
        return t is None or t > cut  # unknown date -> treat as fresh (never silently drop a new offer)
    def spent(o):
        b = o.get("budgetCents") or 0
        return ((o.get("metrics") or {}).get("budgetSpentCents") or 0) / b * 100 if b else 0
    stale = {o["id"] for o in act if o["id"] not in seen and not fresh(o)}
    if stale: print(f"skipped old unseen: {len(stale)}"); seen |= stale
    lim = float(CFG.get("max_spent_pct", 80))
    full = {o["id"] for o in act if o["id"] not in seen and spent(o) >= lim}
    if full: print(f"skipped >={lim:g}% spent: {len(full)}"); seen |= full
    return [o for o in act if o["id"] not in seen][::-1]

# ---------- Telegram ----------
def tg_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(os.environ["TG_SESSION"]), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])

async def channel_state(cl, ch, limit=60):
    """campaign ids already in the channel (recent posts + scheduled queue) and the last scheduled time:
    protects against a lost seen.json write and keeps the posting gap across job restarts"""
    from telethon import functions
    msgs = list(await cl.get_messages(ch, limit=limit))
    try:
        sched = list(getattr(await cl(functions.messages.GetScheduledHistoryRequest(peer=ch, hash=0)), "messages", None) or [])
    except Exception as e:
        print("scheduled history fail", repr(e)[:200]); sched = []
    ids = set()
    for m in msgs + sched:
        for s in [getattr(e, "url", "") or "" for e in getattr(m, "entities", None) or []] + [getattr(m, "message", "") or ""]:
            ids.update(CAMP_RE.findall(s))
    return ids, max((m.date for m in sched if getattr(m, "date", None)), default=None)

async def send(cl, ch, o, cap, when):
    from telethon.errors import FloodWaitError
    img = banner(o)
    for _ in range(3):
        try:
            if img:
                img.seek(0)
                return await asyncio.wait_for(cl.send_file(ch, img, caption=cap, parse_mode="html", schedule=when), 180)
            return await asyncio.wait_for(cl.send_message(ch, cap, parse_mode="html", link_preview=False, schedule=when), 120)
        except FloodWaitError as e:
            if e.seconds > 300: raise
            print("flood wait", e.seconds, "s"); await asyncio.sleep(e.seconds + 2)
        except Exception as e:
            if not img or isinstance(e, (asyncio.TimeoutError, ConnectionError)): raise  # may have been delivered: re-checked before retry
            print("send with banner failed, retrying as text:", repr(e)[:200]); img = None
    raise RuntimeError("send failed after retries")

_alerted = {}
async def alert(cl, text, key, every=3600):
    """problem report to the account's Saved Messages (rate-limited per key)"""
    if time.time() - _alerted.get(key, 0) < every: return
    _alerted[key] = time.time()
    try: await cl.send_message("me", f"⚠️ CR poster: {text}"[:4000], link_preview=False)
    except Exception as e: print("alert fail", repr(e)[:200])

def other_runs_waiting():
    """GitHub Actions: another Telegram workflow (manual poster run, edit, emoji) waits in our concurrency group ->
    finish and let it run (one Telegram session must not be used from two machines at once)"""
    tok, repo, me = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    if not tok or not repo: return False
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/runs", params={"per_page": 50},
                         headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}, timeout=20)
        return any(x.get("status") != "completed" and str(x.get("id")) != me and re.search(r"/(post|edit|emoji)\.yml", x.get("path") or "")
                   for x in r.json().get("workflow_runs", []))
    except Exception as e:
        print("runs check fail", repr(e)[:200]); return False

class Run:
    def __init__(self): self.next_slot = None; self.fails = {}; self.unsure = set()  # ids whose send raised (maybe delivered)

async def post_new(cl, ch, new, seen, st):
    """post offers oldest first; consecutive posts go out >= post_gap_minutes apart (Telegram schedules the later ones)"""
    gap = timedelta(minutes=float(CFG.get("post_gap_minutes", 3)))
    for o in new[: int(CFG.get("max_per_run", 10))]:
        oid = o["id"]
        det = detail(oid)
        if det is None:
            print("offer no longer served by CR, skip:", o.get("name")); seen.add(oid); continue
        try: cap = caption(o, det)
        except Exception as e:  # one odd offer (new CR payout type etc.) must not block the queue
            st.fails[oid] = st.fails.get(oid, 0) + 1
            print("caption fail", st.fails[oid], oid, o.get("name"), repr(e)); traceback.print_exc()
            if st.fails[oid] >= 3:
                seen.add(oid); await alert(cl, f"оффер пропущен, не собирается пост: {o.get('name')} ({oid}): {e!r}", "cap" + oid, 0)
            continue
        if oid in st.unsure and oid in (await channel_state(cl, ch))[0]:
            print("already delivered before the error, not resending:", o["name"]); seen.add(oid); save_seen(seen); continue
        now = datetime.now(timezone.utc)
        when = max(now, st.next_slot or now)
        sched = when if (when - now).total_seconds() > 30 else None
        st.unsure.add(oid)
        await send(cl, ch, o, cap, sched)  # Telegram/network errors propagate: the offer stays unseen and is retried
        st.unsure.discard(oid)
        st.next_slot = when + gap
        seen.add(oid); save_seen(seen)
        print(f"scheduled {sched:%H:%M}Z" if sched else "posted", o["name"])
        await asyncio.sleep(2)

async def run(loop):
    seen = load_seen()
    poll = float(CFG.get("poll_seconds", 60))
    deadline = time.monotonic() + float(CFG.get("loop_minutes", 330)) * 60
    async with tg_client() as cl:
        ch = await cl.get_entity(CFG["channel"])
        if seen is None:  # first run: remember everything, post only the newest N for a test
            act = [o for o in newest() if eligible(o)]
            seen = {o["id"] for o in act[int(CFG.get("first_run_post", 0)):]}
        ids, last = await channel_state(cl, ch)
        if ids - seen: print("already in channel, marking seen:", len(ids - seen)); seen |= ids
        st = Run()
        if last: st.next_slot = last + timedelta(minutes=float(CFG.get("post_gap_minutes", 3)))
        full_at = yield_at = -1e9; errors = 0; synced = -1
        while True:
            t0 = time.monotonic()
            try:
                full = t0 - full_at >= 1800  # full list every 30 min (advertiser stats, stale marks); otherwise 1-2 pages
                camps = newest(None if full else seen)
                if full: org_stats(camps); full_at = t0; print(f"{datetime.now(timezone.utc):%H:%M}Z full refresh: {len(camps)} offers, seen {len(seen)}")
                new = select(camps, seen)
                if new:
                    if not cl.is_connected(): await cl.connect()
                    await post_new(cl, ch, new, seen, st)
                errors = 0
            except Exception as e:
                errors += 1
                print("cycle error", errors, repr(e)[:300]); traceback.print_exc()
                if errors >= 3: await alert(cl, f"{errors} ошибок подряд, последняя: {e!r}", "cycle")
                if not loop: raise
                wait = getattr(e, "seconds", 0)  # Telegram FloodWait: pause instead of hammering
                if isinstance(wait, int) and wait > 0: await asyncio.sleep(min(wait + 2, max(0.0, deadline - time.monotonic())))
            finally:
                if len(seen) != synced:  # also after an error: offers posted before it must be committed
                    save_seen(seen)
                    if git_sync(seen): synced = len(seen)
            if not loop or time.monotonic() > deadline: break
            if t0 - yield_at > 300:
                yield_at = t0
                if other_runs_waiting(): print("another Telegram workflow is waiting, handing over"); break
            await asyncio.sleep(max(5.0, poll - (time.monotonic() - t0)))

async def backfill(items):
    async with tg_client() as cl:
        ch = await cl.get_entity(CFG["channel"])
        st = Run()
        for o, det in items:
            cap = caption(o, det)
            now = datetime.now(timezone.utc); when = max(now, st.next_slot or now)
            await send(cl, ch, o, cap, when if (when - now).total_seconds() > 30 else None)
            st.next_slot = when + timedelta(minutes=float(CFG.get("post_gap_minutes", 3)))
            print("backfill", o["name"]); await asyncio.sleep(2)

def ai_test():
    """python main.py --ai-test : compare AI and rules with hand labels in tests/ai_labels.json (no posting).
    AI_MODEL / AI_FALLBACK_MODEL env vars test another model."""
    data = json.load(open(os.path.join(HERE, "tests", "ai_labels.json"), encoding="utf-8"))
    ai_ok = rule_ok = n_ai = fixed = notes = 0
    models = {}
    for d in data:
        o = d["offer"]; ai = ai_classify(o, {}); rule = footage(o, {})
        rule_ok += rule in d["accept"]
        if ai:
            n_ai += 1; ai_ok += ai["footage"] in d["accept"]; models[ai["model"]] = models.get(ai["model"], 0) + 1
            raw = ai["raw_note"].strip()
            if raw: notes += 1; fixed += raw.rstrip(".") != ai["footage_note"]
        print(f"{o['name'][:45]:45} | ждём {'/'.join(d['accept']):28} | AI {(ai or {}).get('footage','-'):15} {'OK ' if ai and ai['footage'] in d['accept'] else 'ERR'} | правила {rule:15} | ниши AI: {', '.join((ai or {}).get('niches', []))} | {(ai or {}).get('footage_note','')}"
              + (f" [было: {ai['raw_note']}]" if ai and ai["raw_note"].strip().rstrip(".") != ai["footage_note"] else ""))
        time.sleep(7)  # stay under free-tier per-minute limit
    print(f"\nAI ответил на {n_ai}/{len(data)} ({models}), футаж верно: {ai_ok}/{n_ai}; правила: {rule_ok}/{len(data)}; заметок поправлено чисткой: {fixed}/{notes}")

def main():
    if "--ai-test" in sys.argv: return ai_test()
    if "--backfill" in sys.argv:  # test: post the N newest offers again, state untouched
        n = int(sys.argv[sys.argv.index("--backfill") + 1])
        allc = newest(); org_stats(allc)
        pool = [o for o in allc if eligible(o)]
        if "--all-platforms" in sys.argv:  # only offers paying on X, TikTok, Instagram and YouTube
            pool = [o for o in pool if {"x", "tiktok", "instagram", "youtube"} <= set(o.get("platforms") or [])]
        items = [(o, d) for o in pool[:n] for d in [detail(o["id"])] if d is not None][::-1]
        if "--dry" in sys.argv:
            for o, d in items: print(caption(o, d), "\n" + "-" * 40)
        else: asyncio.run(backfill(items))
        return
    if "--dry" in sys.argv:  # what would be posted now; nothing is sent or saved
        seen = load_seen() or set()
        allc = newest(); org_stats(allc)
        for o in select(allc, set(seen))[: int(CFG.get("max_per_run", 10))]:
            d = detail(o["id"])
            if d is not None: print(caption(o, d), "\n" + "-" * 40)
        return
    asyncio.run(run("--loop" in sys.argv))

if __name__ == "__main__":
    main()
