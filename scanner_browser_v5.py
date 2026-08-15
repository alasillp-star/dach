from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import scanner_browser as v4

# Save V4 implementations before patching them.
_original_scan_once = v4.scan_once
_original_keyword_pool = v4.load_short_keyword_pool

# Arab markets only. Algeria stays excluded because it is the destination market.
ARAB_COUNTRIES = [
    "SA", "AE", "KW", "QA", "BH", "OM",
    "EG", "MA", "TN", "LY", "JO", "IQ", "LB", "PS",
    "YE", "SD", "MR",
]

# Arabic short discovery terms first; then Bessahatkom-derived/self-learned Arabic terms.
HIGH_SIGNAL_KEYWORDS = [
    "جهاز", "كريم", "سيروم", "شامبو", "فرشاة", "منظف", "مدلك", "منظم", "حامل",
    "شاحن", "مصباح", "كشاف", "مكنسة", "كاميرا", "نظارات", "بخاخ", "مقشر", "ماسك",
    "قناع", "زيت", "خلاط", "موزع", "مروحة", "مضخة", "لاصقات", "سماعات", "ساعة",
    "ميزان", "قلاية", "بشرة", "شعر", "تنظيف", "ترطيب", "تكثيف", "تساقط", "تجاعيد",
    "تدليك", "مطبخ", "سيارة", "تخزين", "أطفال", "قدم", "ركبة", "ظهر", "رقبة",
    "تخسيس", "تنحيف", "لياقة", "مفاصل", "أسنان", "تبييض", "حبوب", "هالات", "تصبغات",
    "تجاعيد", "رموش", "حواجب", "شفايف", "وجه", "أظافر", "مساج", "راحة", "نوم",
]

# Strong sales CTAs first. These are for choosing the correct outbound link, not search keywords.
SALES_CTA = (
    "shop now", "buy now", "order now", "get yours", "get offer", "purchase",
    "acheter", "achetez", "commander", "commandez",
    "comprar", "compra ahora", "compre agora",
    "اشتري", "اشتر", "اشتري الآن", "اطلب", "اطلب الآن", "تسوق", "تسوق الآن",
    "احصل عليه", "احصل عليها", "احصل الآن", "شراء", "الشراء",
)

SOFT_CTA = (
    "learn more", "see more", "view", "visit", "en savoir plus", "voir plus",
    "اكتشف", "المزيد", "اعرف المزيد", "معرفة المزيد",
)

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def dedupe(values):
    out = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def load_priority_countries():
    return list(ARAB_COUNTRIES)


def load_priority_keywords():
    values = HIGH_SIGNAL_KEYWORDS + _original_keyword_pool()
    out = []
    seen = set()
    for kw in values:
        kw = re.sub(r"\s+", " ", str(kw or "")).strip()
        if not kw or not ARABIC_RE.search(kw):
            continue
        if len(kw.split()) > 2 or len(kw) > 32:
            continue
        key = kw.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
    return out


def build_url(keyword: str, country: str) -> str:
    # Meta gets the 14-day cutoff first; V4 still checks card age itself.
    cutoff = (v4.utcnow() - timedelta(days=v4.MIN_DAYS)).date().isoformat()
    return (
        "https://www.facebook.com/ads/library/?"
        "active_status=active&ad_type=all&"
        f"country={country}&is_targeted_country=false&media_type=video&"
        f"q={quote_plus(keyword)}&search_type=keyword_unordered&locale=ar_AR&"
        f"start_date%5Bmax%5D={cutoff}&"
        "sort_data%5Bmode%5D=total_impressions&"
        "sort_data%5Bdirection%5D=desc"
    )


def external_final_url(url: str) -> str:
    """Return a real external destination URL and reject Meta/internal/DZ links."""
    try:
        current = str(url or "").strip()
        if not current.startswith(("http://", "https://")):
            return ""

        # Unwrap Meta outbound redirects without needing the destination page to load.
        for _ in range(3):
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


def cta_score(label: str) -> int:
    low = re.sub(r"\s+", " ", str(label or "")).strip().casefold()
    if any(x in low for x in SALES_CTA):
        return 120
    if any(x in low for x in SOFT_CTA):
        return 35
    return 0


def rank_card_links(card: dict):
    ranked = []
    seen = set()
    for link in card.get("links") or []:
        link = link or {}
        label = re.sub(r"\s+", " ", str(link.get("text") or "")).strip()
        for raw in (link.get("lynx"), link.get("href"), link.get("rawHref")):
            raw = str(raw or "").strip()
            if not raw.startswith(("http://", "https://")):
                continue
            if raw in seen:
                continue
            seen.add(raw)

            score = cta_score(label)
            low = raw.casefold()
            if "l.facebook.com" in low or "lm.facebook.com" in low:
                score += 45
            if "facebook.com/ads/library" in low:
                score -= 200
            if "facebook.com" not in low:
                score += 25
            ranked.append((score, raw, label))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def verify_landing_in_new_tab(page, card: dict) -> tuple[str, str]:
    """
    Landing URL is mandatory.
    1) Prefer sales CTA links.
    2) Open in a real tab and follow normal redirects.
    3) Capture the final/attempted external navigation URL even if the site itself
       fails to render, is geo-blocked, or times out.
    4) Do not bypass CAPTCHA, login walls, or anti-bot challenges.
    """
    for _score, candidate, label in rank_card_links(card)[:8]:
        # First try to unwrap a Meta redirect immediately.
        direct = external_final_url(candidate)
        if direct:
            # Still open it in a real tab so redirects can improve the URL.
            fallback_url = direct
        else:
            fallback_url = ""

        tab = None
        attempted_external = []
        try:
            tab = page.context.new_page()

            def on_request(req):
                try:
                    if req.is_navigation_request():
                        u = external_final_url(req.url)
                        if u:
                            attempted_external.append(u)
                except Exception:
                    pass

            tab.on("request", on_request)
            print(f"    ↗ VERIFY SALES CTA | {label[:55] or 'link'}", flush=True)

            try:
                tab.goto(candidate, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                # Timeout/403/geo block is acceptable for URL capture; no bypass.
                pass

            try:
                tab.wait_for_timeout(2200)
            except Exception:
                pass

            final_url = external_final_url(tab.url)
            if final_url:
                print(f"    ✅ LANDING VERIFIED | {final_url[:140]}", flush=True)
                return final_url, "Browser final URL"

            if attempted_external:
                final_url = attempted_external[-1]
                print(f"    ✅ LANDING CAPTURED | {final_url[:140]}", flush=True)
                return final_url, "Browser navigation captured"

            if fallback_url:
                print(f"    ✅ LANDING EXTRACTED | {fallback_url[:140]}", flush=True)
                return fallback_url, "Meta redirect extracted"

            # Last public-page fallback: visible outbound anchors only.
            try:
                links = tab.locator("a[href]").evaluate_all(
                    "els => els.map(a => a.href).filter(Boolean).slice(0, 80)"
                )
                for href in links:
                    final_url = external_final_url(href)
                    if final_url:
                        print(f"    ✅ LANDING FOUND | {final_url[:140]}", flush=True)
                        return final_url, "Visible outbound link"
            except Exception:
                pass

        except Exception as exc:
            print(f"    LANDING VERIFY WARNING | {str(exc)[:120]}", flush=True)
        finally:
            if tab is not None:
                try:
                    tab.close()
                except Exception:
                    pass

    return "", ""


def scan_once_with_verified_landings(page, keyword: str, country: str):
    cards = _original_scan_once(page, keyword, country)
    if not cards:
        return cards

    verified = 0
    for card in cards:
        url, source = verify_landing_in_new_tab(page, card)
        card["verified_product_url"] = url
        card["verified_product_source"] = source
        if url:
            verified += 1
    print(f"VERIFIED LANDINGS: {verified}/{len(cards)}", flush=True)
    return cards


def choose_verified_product_url(card: dict) -> tuple[str, str]:
    url = external_final_url(str(card.get("verified_product_url") or ""))
    if not url:
        return "", ""
    return url, str(card.get("verified_product_source") or "Browser verified")


# Apply V5 patches to the working V4 engine.
v4.build_url = build_url
v4.load_global_countries = load_priority_countries
v4.load_short_keyword_pool = load_priority_keywords
v4.scan_once = scan_once_with_verified_landings
v4.choose_product_url = choose_verified_product_url


if __name__ == "__main__":
    cutoff = (v4.utcnow() - timedelta(days=v4.MIN_DAYS)).date().isoformat()
    print("============================================================", flush=True)
    print("WINNING PRODUCTS SCANNER V5 — ARAB MARKETS", flush=True)
    print("MARKETS: ARAB COUNTRIES ONLY — DZ EXCLUDED", flush=True)
    print("SEARCH TERMS: ARABIC 1-WORD / 2-WORD ONLY", flush=True)
    print("CTA PRIORITY: SHOP NOW / BUY NOW / ORDER NOW / اشتري / اطلب / تسوق", flush=True)
    print("META FILTER: ACTIVE + VIDEO + STARTED ON/BEFORE 14-DAY CUTOFF", flush=True)
    print(f"14-DAY CUTOFF: {cutoff}", flush=True)
    print("SORT: TOTAL IMPRESSIONS DESC", flush=True)
    print("LANDING URL: MANDATORY — OPENED/CAPTURED FROM REAL BROWSER NAVIGATION", flush=True)
    print("NO CAPTCHA / LOGIN / ANTI-BOT BYPASS", flush=True)
    print("============================================================", flush=True)
    v4.main()
