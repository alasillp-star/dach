from __future__ import annotations

import csv
import json
import os
import random
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SEED = ROOT / "seed"
CSV_PATH = DATA / "winning_ads.csv"
STATE_PATH = DATA / "scanner_state_v6.json"
LEARNED_PATH = DATA / "keywords_learned_ar.txt"
PROFILE = ROOT / "anonymous_meta_profile_v6"

MIN_DAYS = int(os.getenv("MIN_DAYS", "14"))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30"))
MAX_CARDS = int(os.getenv("MAX_RESULTS", "40"))
SCROLL_ROUNDS = int(os.getenv("SCROLL_ROUNDS", "6"))
RUN_FOREVER = True

ARAB_COUNTRIES = [
    "SA", "AE", "KW", "QA", "BH", "OM",
    "EG", "MA", "TN", "LY", "JO", "IQ", "LB", "PS",
    "YE", "SD", "MR",
]
# Weighted priority: strongest COD/e-commerce markets repeat more often.
COUNTRY_ROTATION = [
    "SA", "AE", "SA", "AE", "KW", "QA", "OM", "BH",
    "EG", "MA", "TN", "JO", "IQ", "LB", "LY", "PS", "MR", "YE", "SD",
]

HIGH_SIGNAL_AR = [
    "جهاز", "كريم", "سيروم", "شامبو", "فرشاة", "منظف", "مدلك", "منظم", "حامل",
    "شاحن", "مصباح", "كشاف", "مكنسة", "كاميرا", "نظارات", "بخاخ", "مقشر", "ماسك",
    "قناع", "زيت", "خلاط", "موزع", "مروحة", "مضخة", "لاصقات", "سماعات", "ساعة",
    "ميزان", "قلاية", "بشرة", "شعر", "تنظيف", "ترطيب", "تكثيف", "تساقط", "تجاعيد",
    "تدليك", "مطبخ", "سيارة", "تخزين", "أطفال", "قدم", "ركبة", "ظهر", "رقبة",
    "تخسيس", "تنحيف", "لياقة", "مفاصل", "أسنان", "تبييض", "هالات", "تصبغات",
    "رموش", "حواجب", "شفايف", "وجه", "أظافر", "مساج", "راحة", "نوم", "رشاقة",
    "للرجال", "للنساء", "منزل", "محمول", "لاسلكي", "قابل للشحن", "ذكي", "أوتوماتيكي",
]

SALES_CTA = [
    "shop now", "buy now", "order now", "get yours", "purchase", "get offer",
    "acheter", "achetez", "commander", "commandez",
    "اشتري الآن", "اشتر الآن", "اطلب الآن", "أطلب الآن", "تسوق الآن",
    "اشتري", "اشتر", "اطلب", "أطلب", "تسوق", "شراء", "الشراء",
    "احصل عليه", "احصل عليها", "احصل الآن",
]
SOFT_CTA = [
    "learn more", "see more", "view", "visit", "en savoir plus", "voir plus",
    "اعرف المزيد", "معرفة المزيد", "المزيد", "اكتشف",
]

STOPWORDS_AR = {
    "هذا", "هذه", "ذلك", "التي", "الذي", "على", "الى", "إلى", "من", "في", "عن", "مع",
    "لك", "لها", "له", "وهو", "وهي", "كما", "كل", "بعد", "قبل", "يمكن", "الآن", "اليوم",
    "عند", "عبر", "بدون", "حتى", "بين", "أو", "او", "ما", "لا", "لم", "لن", "قد", "تم",
    "أفضل", "افضل", "طريقة", "طرق", "منتج", "منتجات", "حل", "طبيعي", "طبيعية", "نتائج",
    "استخدام", "للتخلص", "للحصول", "يساعد", "تساعد", "فعال", "فعالة", "عرض", "خصم",
}
AR_WORD = re.compile(r"[\u0600-\u06FF]{3,}")
ID_PATTERNS = [
    re.compile(r"Library ID:\s*(\d+)", re.I),
    re.compile(r"معرّف المكتبة:\s*(\d+)", re.I),
    re.compile(r"معرف المكتبة:\s*(\d+)", re.I),
]
DATE_PATTERNS = [
    (re.compile(r"Started running on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.I), ["%B %d, %Y", "%b %d, %Y"]),
    (re.compile(r"Started running on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I), ["%d %B %Y", "%d %b %Y"]),
]

HEADERS = [
    "winner_status", "ad_id", "country", "page_name", "page_url",
    "started_on", "days_running", "age_band", "active_status", "media_type",
    "score", "cta_text", "hook", "ad_text",
    "landing_domain", "product_url", "landing_source",
    "video_url", "video_source", "ad_library_url",
    "keyword", "keyword_type", "date_found",
]

def now_utc():
    return datetime.now(timezone.utc)

def log(msg=""):
    print(msg, flush=True)

def safe_host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""

def external_url(url: str) -> str:
    current = str(url or "").strip()
    if not current.startswith(("http://", "https://")):
        return ""
    try:
        for _ in range(4):
            p = urlparse(current)
            host = p.netloc.lower().split(":")[0]
            if host in {"l.facebook.com", "lm.facebook.com"}:
                qs = parse_qs(p.query)
                target = ""
                for key in ("u", "url", "href", "target"):
                    if qs.get(key):
                        target = unquote(qs[key][0])
                        break
                if target:
                    current = target
                    continue
            break
        p = urlparse(current)
        host = p.netloc.lower().split(":")[0]
        if not host:
            return ""
        blocked = ("facebook.com", "instagram.com", "messenger.com", "fb.com")
        if any(host == b or host.endswith("." + b) for b in blocked):
            return ""
        if host.endswith(".dz"):
            return ""
        return current
    except Exception:
        return ""

def age_band(days: int) -> str:
    if days >= 180: return "🔥 180d+"
    if days >= 90: return "🔥 90-179d"
    if days >= 60: return "🔥 60-89d"
    if days >= 30: return "🔥 30-59d"
    return "✅ 14-29d"

def parse_date(text: str):
    for pat, fmts in DATE_PATTERNS:
        m = pat.search(text or "")
        if not m:
            continue
        raw = m.group(1)
        for fmt in fmts:
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None

def extract_id(text: str) -> str:
    for p in ID_PATTERNS:
        m = p.search(text or "")
        if m:
            return m.group(1)
    return ""

def load_state():
    if not STATE_PATH.exists():
        return {"cursor": 0, "attempts": 0, "errors": 0}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"cursor": 0, "attempts": 0, "errors": 0}

def save_state(state):
    DATA.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def read_lines(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out

def keyword_pool():
    raw = []
    for p in sorted(SEED.glob("*.txt")):
        raw.extend(read_lines(p))
    raw.extend(read_lines(LEARNED_PATH))

    counts = Counter()
    pairs = Counter()
    for phrase in raw:
        toks = [x for x in AR_WORD.findall(phrase) if x not in STOPWORDS_AR]
        for t in toks:
            if 3 <= len(t) <= 24:
                counts[t] += 1
        for i in range(len(toks) - 1):
            a, b = toks[i], toks[i+1]
            if a in STOPWORDS_AR or b in STOPWORDS_AR:
                continue
            pair = f"{a} {b}"
            if len(pair) <= 30:
                pairs[pair] += 1

    singles = sorted(counts, key=lambda x: (-counts[x], len(x), x))
    bigrams = sorted((p for p, c in pairs.items() if c >= 2), key=lambda x: (-pairs[x], len(x), x))
    merged = HIGH_SIGNAL_AR + singles + bigrams[:500]
    seen, out = set(), []
    for kw in merged:
        kw = re.sub(r"\s+", " ", kw).strip()
        if not kw or len(kw.split()) > 2 or len(kw) > 32:
            continue
        key = kw.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
    return out

def learn_from_winner(text: str, existing: set[str], limit=10):
    words = [x for x in AR_WORD.findall(text or "") if x not in STOPWORDS_AR and 3 <= len(x) <= 24]
    c = Counter(words)
    out = []
    for w in sorted(c, key=lambda x: (-c[x], len(x), x)):
        k = w.casefold()
        if k in existing:
            continue
        existing.add(k)
        out.append(w)
        if len(out) >= limit:
            break
    return out

def append_learned(items):
    if not items:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    with LEARNED_PATH.open("a", encoding="utf-8") as f:
        for x in items:
            f.write(x + "\n")

def load_existing():
    rows = {}
    if not CSV_PATH.exists():
        return rows
    try:
        with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                ad_id = str(r.get("ad_id") or "").strip()
                if ad_id:
                    rows[ad_id] = {h: r.get(h, "") for h in HEADERS}
    except Exception as exc:
        log(f"CSV WARNING: {exc}")
    return rows

def write_csv(rows):
    DATA.mkdir(parents=True, exist_ok=True)
    vals = list(rows.values())
    vals.sort(key=lambda r: (int(float(r.get("score") or 0)), int(float(r.get("days_running") or 0))), reverse=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        w.writeheader()
        w.writerows(vals)

def git_publish(message: str):
    try:
        subprocess.run(["git", "add", "data/winning_ads.csv", "data/scanner_state_v6.json", "data/keywords_learned_ar.txt"], cwd=ROOT, check=False)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
        if diff.returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=False)
        push = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=ROOT, capture_output=True, text=True)
        if push.returncode != 0:
            log("GITHUB PUSH WARNING: results saved locally; push failed.")
            if push.stderr:
                log(push.stderr.strip()[:300])
    except Exception as exc:
        log(f"GITHUB PUSH WARNING: {exc}")

def build_search_url(keyword: str, country: str, use_date_filter=True):
    base = (
        "https://www.facebook.com/ads/library/?"
        "active_status=active&ad_type=all&"
        f"country={country}&is_targeted_country=false&media_type=video&"
        f"q={quote_plus(keyword)}&search_type=keyword_unordered&locale=en_US&"
        "sort_data%5Bmode%5D=total_impressions&sort_data%5Bdirection%5D=desc"
    )
    if use_date_filter:
        cutoff = (now_utc() - timedelta(days=MIN_DAYS)).date().isoformat()
        base += f"&start_date%5Bmax%5D={cutoff}"
    return base

def dismiss(page):
    for label in [
        "Allow all cookies", "Decline optional cookies", "Only allow essential cookies",
        "Accept All Cookies", "Reject optional cookies", "Close",
    ]:
        try:
            b = page.get_by_role("button", name=label, exact=False)
            if b.count():
                b.first.click(timeout=1200)
                page.wait_for_timeout(300)
        except Exception:
            pass

def detect_block(page):
    try:
        t = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return ""
    for s in ["security check", "confirm you are human", "captcha", "temporarily blocked"]:
        if s in t:
            return s
    return ""

def collect_cards(page):
    return page.evaluate(
        """(maxCards) => {
          const out = [];
          const seen = new Set();
          const divs = Array.from(document.querySelectorAll('div'));
          const idRx = /Library ID:\\s*(\\d+)/i;
          for (const el of divs) {
            let text = (el.innerText || '').trim();
            const m = text.match(idRx);
            if (!m || !text.includes('Started running on') || text.length > 22000) continue;
            const id = m[1];
            if (seen.has(id)) continue;

            const childSame = Array.from(el.children).some(c => {
              const t = (c.innerText || '').trim();
              return idRx.test(t) && t.includes('Started running on');
            });
            if (childSame) continue;

            const links = Array.from(el.querySelectorAll('a[href]')).map(a => ({
              href: a.href || '',
              rawHref: a.getAttribute('href') || '',
              lynx: a.getAttribute('data-lynx-uri') || '',
              text: (a.innerText || a.getAttribute('aria-label') || '').trim()
            }));
            const buttons = Array.from(el.querySelectorAll('button,[role="button"]')).map(b => ({
              text: (b.innerText || b.getAttribute('aria-label') || b.getAttribute('title') || '').trim()
            }));
            const videos = Array.from(el.querySelectorAll('video')).map(v => ({
              currentSrc: v.currentSrc || '',
              src: v.src || '',
              sources: Array.from(v.querySelectorAll('source[src]')).map(s => s.src).filter(Boolean)
            }));
            seen.add(id);
            out.push({ad_id:id, text, links, buttons, videos});
            if (out.length >= maxCards) break;
          }
          return out;
        }""",
        MAX_CARDS,
    )

def scan_page(page, keyword, country, use_date_filter=True):
    url = build_search_url(keyword, country, use_date_filter)
    log(f"BROWSER SEARCH | {country} | {keyword} | {'META-14D' if use_date_filter else 'FALLBACK'}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        log("PAGE WARNING: load timeout; continuing.")
    dismiss(page)
    block = detect_block(page)
    if block:
        log(f"META BLOCKED PAGE: {block} — no bypass attempted")
        return []
    page.wait_for_timeout(4000)
    for _ in range(SCROLL_ROUNDS):
        try:
            page.mouse.wheel(0, 2800)
            page.wait_for_timeout(1200)
        except Exception:
            pass
    cards = collect_cards(page)
    log(f"VISIBLE AD CARDS: {len(cards)}")
    return cards

def cta_rank(label: str):
    low = re.sub(r"\s+", " ", label or "").strip().casefold()
    if any(x in low for x in SALES_CTA):
        return 1000
    if any(x in low for x in SOFT_CTA):
        return 200
    return 0

def mark_cta(page, ad_id: str, token: str):
    return page.evaluate(
        """(cfg) => {
          const needle = 'Library ID: ' + cfg.id;
          const sales = cfg.sales.map(x => x.toLowerCase());
          const soft = cfg.soft.map(x => x.toLowerCase());
          const norm = s => (s || '').toLowerCase().replace(/\\s+/g,' ').trim();
          const txt = el => norm(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '');
          const cards = Array.from(document.querySelectorAll('div'))
            .filter(el => {
              const t = (el.innerText || '').trim();
              return t.includes(needle) && t.includes('Started running on') && t.length < 22000;
            })
            .sort((a,b)=>(a.innerText||'').length-(b.innerText||'').length);

          let best=null, bestScore=-1, bestLabel='', bestHref='';
          for (const card of cards) {
            for (const n of Array.from(card.querySelectorAll('a,button,[role="button"]'))) {
              const label = txt(n);
              let score = 0;
              if (sales.some(x => label.includes(x))) score += 1000;
              else if (soft.some(x => label.includes(x))) score += 200;
              const href = n.href || n.getAttribute('href') || n.getAttribute('data-lynx-uri') || '';
              if (n.tagName === 'BUTTON' || n.getAttribute('role') === 'button') score += 80;
              if (n.tagName === 'A') score += 40;
              if (href && !href.includes('facebook.com/ads/library')) score += 80;
              if (score > bestScore) { best=n; bestScore=score; bestLabel=label; bestHref=href; }
            }
            if (bestScore >= 1000) break;
          }
          if (!best || bestScore < 200) return {found:false};
          best.setAttribute('data-v6-cta', cfg.token);
          try { best.scrollIntoView({block:'center'}); } catch (_) {}
          return {found:true,label:bestLabel,href:bestHref,score:bestScore,tag:best.tagName||''};
        }""",
        {"id": ad_id, "token": token, "sales": SALES_CTA, "soft": SOFT_CTA},
    )

def capture_landing(page, card):
    ad_id = card["ad_id"]
    token = "v6cta-" + ad_id
    info = mark_cta(page, ad_id, token)
    if not info or not info.get("found"):
        return "", "", "cta_not_found"

    label = str(info.get("label") or "CTA")
    fallback = external_url(str(info.get("href") or ""))
    log(f"    🖱 CLICK CTA | {label[:70]}")
    context = page.context
    before = list(context.pages)
    nav = []

    def on_req(req):
        try:
            if req.is_navigation_request():
                u = external_url(req.url)
                if u:
                    nav.append(u)
        except Exception:
            pass

    try:
        page.on("request", on_req)
    except Exception:
        pass

    search_url = page.url
    new_pages = []
    try:
        loc = page.locator(f'[data-v6-cta="{token}"]').first
        try:
            loc.click(timeout=7000)
        except Exception:
            loc.click(timeout=5000, force=True)

        page.wait_for_timeout(2200)
        new_pages = [p for p in context.pages if p not in before]

        for pop in new_pages:
            try:
                pop.wait_for_load_state("domcontentloaded", timeout=7000)
            except Exception:
                pass
            try:
                pop.wait_for_timeout(700)
            except Exception:
                pass
            u = external_url(pop.url)
            if u:
                return u, label, "Clicked CTA - new tab"

        u = external_url(page.url)
        if u:
            return u, label, "Clicked CTA - same tab"

        if nav:
            return nav[-1], label, "Clicked CTA - navigation request"

        if fallback:
            return fallback, label, "CTA href fallback"

        return "", label, "cta_click_no_external_url"
    finally:
        try:
            page.remove_listener("request", on_req)
        except Exception:
            pass
        for p in new_pages:
            try:
                p.close()
            except Exception:
                pass
        if external_url(page.url):
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
            except Exception:
                pass

def extract_video_url(card):
    candidates = []
    for v in card.get("videos") or []:
        vals = [v.get("currentSrc"), v.get("src")] + list(v.get("sources") or [])
        for u in vals:
            u = str(u or "")
            if u.startswith(("http://", "https://")):
                score = 0
                low = u.lower()
                if ".mp4" in low: score += 30
                if "fbcdn.net" in low: score += 10
                candidates.append((score, u))
    if not candidates:
        return "", "Ad Library only"
    candidates.sort(reverse=True)
    return candidates[0][1], "Direct DOM"

def page_info(card):
    for l in card.get("links") or []:
        href = str(l.get("href") or "")
        txt = re.sub(r"\s+", " ", str(l.get("text") or "")).strip()
        try:
            p = urlparse(href)
        except Exception:
            continue
        if "facebook.com" in p.netloc.lower() and "/ads/library" not in p.path.lower() and txt and len(txt) <= 120:
            return txt, href
    return "", ""

def hook_from_text(text, page_name):
    lines = [re.sub(r"\s+", " ", x).strip() for x in (text or "").splitlines() if x.strip()]
    banned = ("Library ID:", "Started running on", "Active", "Sponsored", "See ad details")
    for line in lines:
        if page_name and line == page_name:
            continue
        if any(line.startswith(x) for x in banned):
            continue
        if 8 <= len(line) <= 180:
            return line
    return ""

def process_card(page, card, keyword, country):
    text = str(card.get("text") or "")
    ad_id = card.get("ad_id") or extract_id(text)
    started = parse_date(text)
    if not ad_id:
        return None, "no_ad_id"
    if not started:
        return None, "date_unparsed"

    days = (now_utc() - started).days
    if days < MIN_DAYS:
        return None, f"too_new:{days}"

    product_url, cta_text, landing_source = capture_landing(page, card)
    if not product_url:
        return None, landing_source or "no_landing"

    video_url, video_source = extract_video_url(card)
    p_name, p_url = page_info(card)
    hook = hook_from_text(text, p_name)

    score = min(days, 365) + 30
    if video_url: score += 20
    if cta_rank(cta_text) >= 1000: score += 25
    if days >= 30: score += 20
    if days >= 60: score += 20
    if days >= 90: score += 20

    return {
        "winner_status": "✅ WINNER" if video_url else "🟡 WINNER — VIDEO LINK PENDING",
        "ad_id": ad_id,
        "country": country,
        "page_name": p_name,
        "page_url": p_url,
        "started_on": started.date().isoformat(),
        "days_running": days,
        "age_band": age_band(days),
        "active_status": "ACTIVE",
        "media_type": "VIDEO",
        "score": score,
        "cta_text": cta_text,
        "hook": hook,
        "ad_text": re.sub(r"\s+", " ", text).strip(),
        "landing_domain": safe_host(product_url),
        "product_url": product_url,
        "landing_source": landing_source,
        "video_url": video_url,
        "video_source": video_source,
        "ad_library_url": f"https://www.facebook.com/ads/library/?id={ad_id}",
        "keyword": keyword,
        "keyword_type": "1-word" if len(keyword.split()) == 1 else "2-word",
        "date_found": now_utc().isoformat(timespec="seconds"),
    }, "winner"

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)
    state = load_state()
    rows = load_existing()
    write_csv(rows)

    log("=" * 66)
    log("WINNING PRODUCTS SCANNER V6 — CLEAN FINAL BUILD")
    log("ANONYMOUS META AD LIBRARY — NO FACEBOOK ACCOUNT")
    log("ARAB MARKETS ONLY — DZ EXCLUDED")
    log("ARABIC SHORT KEYWORDS — 1/2 WORDS")
    log("FILTER: ACTIVE + VIDEO + >=14 DAYS")
    log("CTA: REAL BUTTON CLICK — SHOP/BUY/ORDER/اشتري/اطلب/تسوق")
    log("LANDING URL: MANDATORY")
    log("VIDEO URL: DIRECT WHEN META EXPOSES IT")
    log("=" * 66)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            headless=False,
            locale="en-US",
            viewport={"width": 1360, "height": 920},
            args=["--disable-notifications", "--lang=en-US"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        while RUN_FOREVER:
            started_loop = time.monotonic()
            try:
                keywords = keyword_pool()
                if not keywords:
                    raise RuntimeError("No Arabic keywords available")

                cursor = int(state.get("cursor", 0))
                keyword = keywords[(cursor * 37) % len(keywords)]
                country = COUNTRY_ROTATION[(cursor * 7) % len(COUNTRY_ROTATION)]
                state["cursor"] = cursor + 1
                state["attempts"] = int(state.get("attempts", 0)) + 1
                state["last_keyword"] = keyword
                state["last_country"] = country
                state["last_attempt"] = now_utc().isoformat(timespec="seconds")
                save_state(state)

                cards = scan_page(page, keyword, country, True)
                if not cards:
                    log("META-14D RETURNED 0 — FALLBACK WITHOUT DATE URL FILTER")
                    cards = scan_page(page, keyword, country, False)

                added = 0
                rejects = Counter()
                keyword_keys = {k.casefold() for k in keywords}

                for i, card in enumerate(cards, start=1):
                    ad_id = card.get("ad_id") or "?"
                    log(f"  CARD {i}/{len(cards)} | Ad {ad_id}")
                    if ad_id in rows:
                        rejects["duplicate"] += 1
                        continue

                    row, reason = process_card(page, card, keyword, country)
                    if not row:
                        rejects[reason] += 1
                        log(f"    ⏭ REJECTED | {reason}")
                        continue

                    rows[row["ad_id"]] = row
                    added += 1
                    learned = learn_from_winner(row["ad_text"], keyword_keys)
                    append_learned(learned)
                    log(
                        f"    ✅ WINNER SAVED | {row['days_running']}d | "
                        f"Landing ✅ | Video {'✅' if row['video_url'] else '⚠️'} | "
                        f"{row['product_url'][:110]}"
                    )

                state["added_last_run"] = added
                state["total_ads"] = len(rows)
                state["last_rejections"] = dict(rejects)
                save_state(state)

                if added:
                    write_csv(rows)
                    git_publish(f"V6 add {added} winning ads")
                log(f"RESULT | +{added} WINNERS | TOTAL {len(rows)} | REJECTED {dict(rejects)}")

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                state["errors"] = int(state.get("errors", 0)) + 1
                state["last_error"] = str(exc)
                save_state(state)
                log(f"SCANNER ERROR: {exc}")

            elapsed = time.monotonic() - started_loop
            wait_for = max(5, INTERVAL_SECONDS - int(elapsed))
            log(f"NEXT SEARCH IN {wait_for}s")
            time.sleep(wait_for)

if __name__ == "__main__":
    main()
