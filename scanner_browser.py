from __future__ import annotations

import csv
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import scanner as base

PROFILE = Path("anonymous_meta_profile")
CSV_PATH = Path("data/winning_ads.csv")
GLOBAL_COUNTRIES_PATH = Path("countries_global.txt")
LEARNED_PATH = Path("data/keywords_learned_ar.txt")

MIN_DAYS = int(os.getenv("MIN_DAYS", "14"))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30"))
RUN_SECONDS = int(os.getenv("RUN_SECONDS", "20400"))
SCROLL_ROUNDS = int(os.getenv("SCROLL_ROUNDS", "5"))
MAX_CARDS = int(os.getenv("MAX_RESULTS", "30"))

HEADERS = [
    "winner_status",
    "ad_id",
    "country",
    "market_group",
    "page_name",
    "page_url",
    "started_on",
    "days_running",
    "age_band",
    "active_status",
    "media_type",
    "score",
    "hook",
    "ad_text",
    "landing_domain",
    "product_url",
    "video_url",
    "video_source",
    "ad_library_url",
    "keyword",
    "keyword_type",
    "date_found",
]

MONTH_FORMATS = [
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
]

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ\u0600-\u06FF]{3,}")

SEARCH_STOPWORDS = {
    "هذا", "هذه", "ذلك", "التي", "الذي", "على", "الى", "إلى", "من", "في", "عن", "مع",
    "لك", "لها", "له", "وهو", "وهي", "كما", "كل", "بعد", "قبل", "يمكن", "الآن", "اليوم",
    "عند", "عبر", "بدون", "حتى", "بين", "أو", "او", "ما", "لا", "لم", "لن", "قد", "تم",
    "أفضل", "افضل", "طريقة", "طرق", "منتج", "منتجات", "حل", "طبيعي", "طبيعية", "نتائج",
    "استخدام", "للتخلص", "للحصول", "يساعد", "تساعد", "فعال", "فعالة",
    "the", "and", "for", "with", "from", "your", "this", "that", "best", "product",
    "products", "solution", "natural", "new", "now", "pour", "avec", "dans", "les", "des",
    "une", "un", "meilleur", "produit", "productos", "produto",
}

CURATED_SHORT_KEYWORDS = [
    "جهاز", "كريم", "سيروم", "شامبو", "فرشاة", "منظف", "مدلك", "منظم", "حامل", "شاحن",
    "مصباح", "كشاف", "مكنسة", "كاميرا", "نظارات", "بخاخ", "مقشر", "ماسك", "قناع", "زيت",
    "خلاط", "موزع", "مروحة", "مضخة", "لاصقات", "سماعات", "ساعة", "ميزان", "قلاية",
    "بشرة", "شعر", "تنظيف", "ترطيب", "تكثيف", "تساقط", "تجاعيد", "تدليك", "مطبخ",
    "سيارة", "تخزين", "أطفال", "قدم", "ركبة", "ظهر", "رقبة",
    "gadget", "cleaner", "organizer", "massager", "serum", "cream", "shampoo", "brush",
    "lamp", "flashlight", "charger", "holder", "vacuum", "trimmer", "shaver", "projector",
    "humidifier", "sprayer", "dispenser", "storage", "kitchen", "beauty", "car", "pet",
    "baby", "solar", "portable", "rechargeable", "cordless", "magnetic", "waterproof",
    "appareil", "nettoyeur", "organisateur", "masseur", "sérum", "crème", "shampoing",
    "brosse", "lampe", "chargeur", "aspirateur", "cuisine", "beauté", "voiture", "solaire",
    "limpiador", "organizador", "masajeador", "suero", "crema", "champú", "cepillo",
    "lámpara", "cargador", "aspiradora", "limpador", "massageador", "escova",
]

MARKET_GROUPS = {
    "US": "Tier 1", "GB": "Tier 1", "CA": "Tier 1", "AU": "Tier 1",
    "FR": "Europe", "DE": "Europe", "IT": "Europe", "ES": "Europe", "NL": "Europe",
    "BE": "Europe", "PT": "Europe", "PL": "Europe", "RO": "Europe", "CZ": "Europe",
    "GR": "Europe", "SE": "Europe", "NO": "Europe", "DK": "Europe", "FI": "Europe",
    "SA": "GCC", "AE": "GCC", "KW": "GCC", "QA": "GCC", "BH": "GCC", "OM": "GCC",
    "EG": "MENA", "MA": "MENA", "TN": "MENA", "LY": "MENA", "JO": "MENA",
    "IQ": "MENA", "LB": "MENA", "PS": "MENA",
    "BR": "LatAm", "MX": "LatAm", "CO": "LatAm", "CL": "LatAm", "AR": "LatAm", "PE": "LatAm",
    "TR": "Growth", "ZA": "Growth", "IN": "Growth", "ID": "Growth", "MY": "Growth",
    "PH": "Growth", "TH": "Growth", "VN": "Growth", "PK": "Growth",
}

CTA_SIGNALS = (
    "shop now", "buy now", "order now", "learn more", "get offer", "sign up",
    "commander", "acheter", "en savoir plus", "comprar", "comprar ahora",
    "saiba mais", "compre agora", "اطلب", "اشتري", "تسوق",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_url(keyword: str, country: str) -> str:
    return (
        "https://www.facebook.com/ads/library/?"
        "active_status=active&ad_type=all&"
        f"country={country}&is_targeted_country=false&media_type=video&"
        f"q={quote_plus(keyword)}&search_type=keyword_unordered&locale=en_US"
    )


def load_global_countries() -> list[str]:
    if GLOBAL_COUNTRIES_PATH.exists():
        vals = [x.strip().upper() for x in GLOBAL_COUNTRIES_PATH.read_text(encoding="utf-8").splitlines()]
        vals = [x for x in vals if x and not x.startswith("#") and x != "DZ"]
        if vals:
            return list(dict.fromkeys(vals))
    return [x for x in MARKET_GROUPS if x != "DZ"]


def normalize_token(token: str) -> str:
    return re.sub(r"\s+", " ", token.strip(" -_/.,:;!?()[]{}\"'")).strip()


def load_short_keyword_pool() -> list[str]:
    raw: list[str] = []
    for path in sorted(base.SEED_DIR.glob("keywords_ar_*.txt")):
        raw.extend(base.read_lines(path))
    raw.extend(base.read_lines(LEARNED_PATH))

    counts = Counter()
    bigrams = Counter()

    for phrase in raw:
        tokens = [normalize_token(x) for x in WORD_RE.findall(phrase)]
        tokens = [x for x in tokens if x and x.casefold() not in SEARCH_STOPWORDS]
        for token in tokens:
            if 3 <= len(token) <= 24:
                counts[token] += 1
        for i in range(len(tokens) - 1):
            pair = f"{tokens[i]} {tokens[i + 1]}"
            if len(pair) <= 28:
                bigrams[pair] += 1

    singles = sorted(counts, key=lambda x: (-counts[x], len(x), x.casefold()))
    pairs = sorted(
        (p for p, c in bigrams.items() if c >= 2),
        key=lambda x: (-bigrams[x], len(x), x.casefold()),
    )

    merged = CURATED_SHORT_KEYWORDS + singles + pairs[:350]
    out = []
    seen = set()
    for kw in merged:
        kw = normalize_token(kw)
        if not kw:
            continue
        if len(kw.split()) > 2 or len(kw) > 32:
            continue
        key = kw.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
    return out


def keyword_type(keyword: str) -> str:
    return "1-word" if len(keyword.split()) == 1 else "2-word"


def unwrap_external(url: str) -> str:
    if not url:
        return ""
    try:
        current = str(url)
        for _ in range(3):
            p = urlparse(current)
            host = p.netloc.lower().split(":")[0]
            if host in {"l.facebook.com", "lm.facebook.com"}:
                qs = parse_qs(p.query)
                if qs.get("u"):
                    current = unquote(qs["u"][0])
                    continue
            break
        p = urlparse(current)
        host = p.netloc.lower().split(":")[0]
        blocked = ("facebook.com", "instagram.com", "messenger.com", "fb.com")
        if any(host == b or host.endswith("." + b) for b in blocked):
            return ""
        if host.endswith(".dz"):
            return ""
        if p.scheme in {"http", "https"} and host:
            return current
    except Exception:
        pass
    return ""


def parse_started(text: str):
    patterns = [
        r"Started running on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        r"Started running on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        raw = m.group(1)
        for fmt in MONTH_FORMATS:
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None


def age_band(days: int) -> str:
    if days >= 180:
        return "🔥 180d+"
    if days >= 90:
        return "🔥 90-179d"
    if days >= 60:
        return "🔥 60-89d"
    if days >= 30:
        return "🔥 30-59d"
    return "✅ 14-29d"


def market_group(country: str) -> str:
    return MARKET_GROUPS.get(country, "Other")


def landing_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""


def extract_cards(page):
    return page.evaluate(
        """(maxCards) => {
          const all = Array.from(document.querySelectorAll('div'));
          const picked = [];
          for (const el of all) {
            const text = (el.innerText || '').trim();
            if (!text.includes('Library ID:')) continue;
            if (!text.includes('Started running on')) continue;
            if (text.length > 14000) continue;

            const childHasBoth = Array.from(el.children).some(c => {
              const t = (c.innerText || '').trim();
              return t.includes('Library ID:') && t.includes('Started running on');
            });
            if (childHasBoth) continue;

            const links = Array.from(el.querySelectorAll('a[href]')).map(a => ({
              href: a.href || '',
              rawHref: a.getAttribute('href') || '',
              lynx: a.getAttribute('data-lynx-uri') || '',
              text: (a.innerText || a.getAttribute('aria-label') || '').trim()
            }));

            const videos = [];
            for (const v of Array.from(el.querySelectorAll('video'))) {
              const sources = Array.from(v.querySelectorAll('source[src]')).map(s => s.src).filter(Boolean);
              videos.push({
                currentSrc: v.currentSrc || '',
                src: v.src || '',
                sources,
                poster: v.poster || ''
              });
            }

            const mediaSrcs = Array.from(el.querySelectorAll('[src]'))
              .map(x => x.src || '')
              .filter(x => x && (x.includes('.mp4') || x.includes('video') || x.includes('fbcdn.net')));

            picked.push({text, links, videos, mediaSrcs});
            if (picked.length >= maxCards) break;
          }
          return picked;
        }""",
        MAX_CARDS,
    )


def choose_page(card: dict) -> tuple[str, str]:
    for link in card.get("links") or []:
        href = str((link or {}).get("href") or "")
        text = re.sub(r"\s+", " ", str((link or {}).get("text") or "")).strip()
        try:
            p = urlparse(href)
            host = p.netloc.lower()
            path = p.path.lower()
        except Exception:
            continue
        if "facebook.com" not in host:
            continue
        if "/ads/library" in path or "/privacy" in path or "/policies" in path:
            continue
        if not text or len(text) > 120:
            continue
        return text, href
    return "", ""


def choose_product_url(card: dict) -> tuple[str, str]:
    candidates = []
    for link in card.get("links") or []:
        link = link or {}
        hrefs = [link.get("lynx"), link.get("href"), link.get("rawHref")]
        label = re.sub(r"\s+", " ", str(link.get("text") or "")).strip()
        for href in hrefs:
            candidate = unwrap_external(str(href or ""))
            if not candidate:
                continue
            score = 0
            low = label.casefold()
            if any(signal in low for signal in CTA_SIGNALS):
                score += 20
            if candidate.startswith("https://"):
                score += 2
            candidates.append((score, candidate, label))
    if not candidates:
        return "", ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def choose_video_url(card: dict) -> tuple[str, str]:
    candidates = []
    for video in card.get("videos") or []:
        video = video or {}
        values = [video.get("currentSrc"), video.get("src")] + list(video.get("sources") or [])
        for src in values:
            src = str(src or "")
            if not src.startswith(("http://", "https://")):
                continue
            score = 0
            low = src.lower()
            if ".mp4" in low:
                score += 20
            if "fbcdn.net" in low:
                score += 10
            candidates.append((score, src))
    for src in card.get("mediaSrcs") or []:
        src = str(src or "")
        if src.startswith(("http://", "https://")):
            low = src.lower()
            if ".mp4" in low or "video" in low:
                candidates.append((15, src))
    if not candidates:
        return "", "Ad Library only"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], "Direct"


def extract_hook(raw_text: str, page_name: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in str(raw_text).splitlines() if x.strip()]
    banned_starts = (
        "Library ID:", "Started running on", "Active", "Sponsored", "Platforms",
        "See ad details", "Multiple versions", "This ad has", "EU transparency",
    )
    for line in lines:
        if page_name and line == page_name:
            continue
        if any(line.startswith(x) for x in banned_starts):
            continue
        if 8 <= len(line) <= 180:
            return line
    return ""


def normalize_card(card: dict, keyword: str, country: str):
    raw_text = str(card.get("text") or "")
    text = re.sub(r"\s+", " ", raw_text).strip()
    if not text:
        return None, "empty"

    m = re.search(r"Library ID:\s*(\d+)", text, re.I)
    if not m:
        return None, "no_ad_id"
    ad_id = m.group(1)

    started = parse_started(text)
    if not started:
        return None, "date_unparsed"

    days = (utcnow() - started).days
    if days < MIN_DAYS:
        return None, f"too_new:{days}"

    product_url, _cta_text = choose_product_url(card)
    if not product_url:
        return None, "no_landing"

    video_url, video_source = choose_video_url(card)
    page_name, page_url = choose_page(card)
    hook = extract_hook(raw_text, page_name)
    now = utcnow()

    score = min(days, 365)
    if video_url:
        score += 20
    if product_url:
        score += 15
    if days >= 30:
        score += 20
    if days >= 60:
        score += 20
    if days >= 90:
        score += 20

    winner_status = "✅ WINNER"
    if not video_url:
        winner_status = "🟡 WINNER — VIDEO LINK PENDING"

    return {
        "winner_status": winner_status,
        "ad_id": ad_id,
        "country": country,
        "market_group": market_group(country),
        "page_name": page_name,
        "page_url": page_url,
        "started_on": started.date().isoformat(),
        "days_running": days,
        "age_band": age_band(days),
        "active_status": "ACTIVE",
        "media_type": "VIDEO",
        "score": score,
        "hook": hook,
        "ad_text": text,
        "landing_domain": landing_domain(product_url),
        "product_url": product_url,
        "video_url": video_url,
        "video_source": video_source,
        "ad_library_url": f"https://www.facebook.com/ads/library/?id={ad_id}",
        "keyword": keyword,
        "keyword_type": keyword_type(keyword),
        "date_found": now.isoformat(timespec="seconds"),
    }, "winner"


def load_existing_v2() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not CSV_PATH.exists():
        return rows
    try:
        with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
            for old in csv.DictReader(f):
                ad_id = str(old.get("ad_id") or "").strip()
                if not ad_id:
                    continue
                row = {h: old.get(h, "") for h in HEADERS}
                if not row["winner_status"]:
                    try:
                        d = int(float(old.get("days_running") or 0))
                    except Exception:
                        d = 0
                    row["winner_status"] = "✅ WINNER" if d >= MIN_DAYS else "LEGACY"
                rows[ad_id] = row
    except Exception as exc:
        print(f"CSV LOAD WARNING: {exc}", flush=True)
    return rows


def write_csv_v2(rows: dict[str, dict]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    values = list(rows.values())

    def score_key(r):
        try:
            score = int(float(r.get("score") or 0))
        except Exception:
            score = 0
        try:
            days = int(float(r.get("days_running") or 0))
        except Exception:
            days = 0
        return score, days, str(r.get("date_found") or "")

    values.sort(key=score_key, reverse=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(values)


def learn_short_from_winner(text: str, existing: set[str], limit: int = 8) -> list[str]:
    tokens = [normalize_token(x) for x in WORD_RE.findall(text)]
    tokens = [x for x in tokens if x and x.casefold() not in SEARCH_STOPWORDS and 3 <= len(x) <= 24]
    counts = Counter(tokens)
    ranked = sorted(counts, key=lambda x: (-counts[x], len(x), x.casefold()))
    out = []
    for token in ranked:
        key = token.casefold()
        if key in existing:
            continue
        existing.add(key)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def append_learned_short(items: list[str]) -> int:
    if not items:
        return 0
    LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEARNED_PATH.open("a", encoding="utf-8") as f:
        for item in items:
            f.write(item + "\n")
    return len(items)


def dismiss_dialogs(page):
    labels = [
        "Allow all cookies", "Decline optional cookies", "Only allow essential cookies",
        "Accept All Cookies", "Reject optional cookies", "Close",
    ]
    for label in labels:
        try:
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count() > 0:
                btn.first.click(timeout=1500)
                time.sleep(0.5)
        except Exception:
            pass


def detect_block(page):
    try:
        txt = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return ""
    signals = ["security check", "confirm you are human", "captcha", "temporarily blocked"]
    for s in signals:
        if s in txt:
            return s
    return ""


def scan_once(page, keyword: str, country: str):
    url = build_url(keyword, country)
    print(f"BROWSER SEARCH | {country} | {keyword} | {keyword_type(keyword)}", flush=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        print("PAGE WARNING: load timeout; continuing with rendered page", flush=True)

    dismiss_dialogs(page)
    block = detect_block(page)
    if block:
        print(f"BROWSER BLOCKED: Meta displayed {block}; no bypass attempted", flush=True)
        return []

    try:
        page.wait_for_timeout(4500)
        for _ in range(SCROLL_ROUNDS):
            page.mouse.wheel(0, 2600)
            page.wait_for_timeout(1400)
    except Exception:
        pass

    cards = extract_cards(page)
    print(f"VISIBLE AD CARDS: {len(cards)}", flush=True)
    return cards


def main():
    PROFILE.mkdir(parents=True, exist_ok=True)
    state = base.load_state()
    existing = load_existing_v2()
    write_csv_v2(existing)
    countries = load_global_countries()
    if not countries:
        raise SystemExit("No global countries configured")

    started_loop = time.monotonic()

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE),
                channel="chrome",
                headless=False,
                locale="en-US",
                viewport={"width": 1360, "height": 920},
                args=["--disable-notifications", "--lang=en-US"],
            )
        except Exception as exc:
            raise SystemExit(f"Could not launch Google Chrome with Playwright: {exc}")

        page = context.pages[0] if context.pages else context.new_page()
        print("META MODE: anonymous real Chrome browser — GLOBAL markets — NO Facebook login", flush=True)
        print(f"FILTER: ACTIVE + VIDEO + >= {MIN_DAYS} DAYS + LANDING PAGE", flush=True)

        while time.monotonic() - started_loop < RUN_SECONDS:
            loop_started = time.monotonic()
            keywords = load_short_keyword_pool()
            if not keywords:
                raise SystemExit("No short keywords found")

            cursor = int(state.get("browser_cursor_v4", 0))
            keyword = keywords[(cursor * 29) % len(keywords)]
            country = countries[(cursor * 17) % len(countries)]
            state["browser_cursor_v4"] = cursor + 1
            state["attempts"] = int(state.get("attempts", 0)) + 1
            state["last_keyword"] = keyword
            state["last_country"] = country
            state["last_attempt"] = utcnow().isoformat(timespec="seconds")

            added = 0
            learned = 0
            reject_counts = Counter()

            try:
                cards = scan_once(page, keyword, country)
                keyword_keys = {k.casefold() for k in keywords}

                for card in cards:
                    row, reason = normalize_card(card, keyword, country)
                    if not row:
                        reject_counts[reason] += 1
                        if reason.startswith("too_new:"):
                            print(f"  ⏭ REJECTED | {reason.split(':', 1)[1]} days (<{MIN_DAYS})", flush=True)
                        continue

                    if row["ad_id"] in existing:
                        reject_counts["duplicate"] += 1
                        continue

                    existing[row["ad_id"]] = row
                    added += 1

                    new_terms = learn_short_from_winner(row["ad_text"], keyword_keys)
                    learned += append_learned_short(new_terms)

                    video_flag = "✅" if row["video_url"] else "⚠️"
                    print(
                        f"  ✅ WINNER SAVED | {row['days_running']}d | {country} | "
                        f"{row['page_name'][:35]} | Landing ✅ | Video {video_flag}",
                        flush=True,
                    )

                state["added_last_run"] = added
                state["total_ads"] = len(existing)
                state["learned_last_run"] = learned
                state["last_rejections"] = dict(reject_counts)
                base.save_state(state)

                if added:
                    write_csv_v2(existing)
                    base.publish_to_github(f"Add {added} global browser winners")
                    print(
                        f"RESULT | ✅ +{added} WINNERS | TOTAL {len(existing)} | "
                        f"LEARNED {learned} | REJECTED {dict(reject_counts)}",
                        flush=True,
                    )
                else:
                    print(f"RESULT | +0 | REJECTED {dict(reject_counts)}", flush=True)

            except Exception as exc:
                state["errors"] = int(state.get("errors", 0)) + 1
                state["last_error"] = str(exc)
                base.save_state(state)
                print(f"BROWSER SEARCH ERROR: {exc}", flush=True)

            elapsed = time.monotonic() - loop_started
            wait_for = max(5, INTERVAL_SECONDS - int(elapsed))
            print(f"NEXT SEARCH IN {wait_for}s", flush=True)
            time.sleep(wait_for)

        try:
            context.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
