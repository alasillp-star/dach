from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import quote_plus, urlparse

import scanner_browser as v4

# Save V4 implementations before patching them.
_original_scan_once = v4.scan_once
_original_keyword_pool = v4.load_short_keyword_pool
_original_country_pool = v4.load_global_countries

# Search the strongest product-discovery markets first, then rotate through the rest.
PRIORITY_COUNTRIES = [
    "US", "GB", "CA", "AU",
    "FR", "DE", "IT", "ES", "NL", "BE", "PT",
    "SA", "AE", "KW", "QA", "BH", "OM",
    "BR", "MX", "CO", "CL",
    "MA", "TN", "EG", "TR", "ZA",
]

# Short, broad terms first. The huge Bessahatkom-derived/self-learning pool is appended after these.
HIGH_SIGNAL_KEYWORDS = [
    "portable", "rechargeable", "wireless", "automatic", "electric", "smart", "mini",
    "cordless", "magnetic", "waterproof", "solar", "cleaner", "massager", "organizer",
    "projector", "vacuum", "trimmer", "brush", "lamp", "holder", "dispenser", "storage",
    "kitchen", "beauty", "car", "pet", "baby", "gadget",
    "appareil", "portable", "rechargeable", "sans fil", "automatique", "électrique",
    "nettoyeur", "masseur", "organisateur", "aspirateur", "brosse", "lampe", "cuisine",
    "جهاز", "كريم", "سيروم", "شامبو", "فرشاة", "منظف", "مدلك", "منظم", "حامل",
    "شاحن", "مصباح", "كشاف", "مكنسة", "بخاخ", "مقشر", "خلاط", "مروحة", "مطبخ",
    "سيارة", "تنظيف", "تدليك", "تخزين",
    "limpiador", "organizador", "masajeador", "aspiradora", "cepillo", "lámpara",
    "limpador", "massageador", "escova",
]

CTA_HINTS = (
    "shop", "buy", "order", "learn", "get", "view", "see", "visit",
    "acheter", "commander", "voir", "découvrir", "en savoir",
    "comprar", "ver", "saiba", "compre", "اطلب", "اشتري", "تسوق", "المزيد",
)


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
    return dedupe(PRIORITY_COUNTRIES + _original_country_pool())


def load_priority_keywords():
    # Keep one/two-word keywords only.
    values = HIGH_SIGNAL_KEYWORDS + _original_keyword_pool()
    return [x for x in dedupe(values) if len(x.split()) <= 2 and len(x) <= 32]


def build_url(keyword: str, country: str) -> str:
    # Meta receives the 14-day cutoff in the search URL first.
    # V4 still parses every visible card and independently rejects anything < MIN_DAYS.
    cutoff = (v4.utcnow() - timedelta(days=v4.MIN_DAYS)).date().isoformat()
    return (
        "https://www.facebook.com/ads/library/?"
        "active_status=active&ad_type=all&"
        f"country={country}&is_targeted_country=false&media_type=video&"
        f"q={quote_plus(keyword)}&search_type=keyword_unordered&locale=en_US&"
        f"start_date%5Bmax%5D={cutoff}&"
        "sort_data%5Bmode%5D=total_impressions&"
        "sort_data%5Bdirection%5D=desc"
    )


def external_final_url(url: str) -> str:
    """Return only a real external landing URL."""
    try:
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return ""
        p = urlparse(url)
        host = p.netloc.lower().split(":")[0]
        if not host:
            return ""
        blocked = ("facebook.com", "instagram.com", "messenger.com", "fb.com")
        if any(host == b or host.endswith("." + b) for b in blocked):
            return ""
        if host.endswith(".dz"):
            return ""
        return url
    except Exception:
        return ""


def rank_card_links(card: dict):
    ranked = []
    seen = set()
    for link in card.get("links") or []:
        link = link or {}
        label = re.sub(r"\s+", " ", str(link.get("text") or "")).strip()
        low_label = label.casefold()
        for raw in (link.get("lynx"), link.get("href"), link.get("rawHref")):
            raw = str(raw or "").strip()
            if not raw.startswith(("http://", "https://")):
                continue
            if raw in seen:
                continue
            seen.add(raw)
            score = 0
            if any(hint in low_label for hint in CTA_HINTS):
                score += 50
            low = raw.casefold()
            if "l.facebook.com" in low or "lm.facebook.com" in low:
                score += 35  # likely Meta outbound redirect
            if "facebook.com/ads/library" in low:
                score -= 100
            if "facebook.com" not in low:
                score += 20
            ranked.append((score, raw, label))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def verify_landing_in_new_tab(page, card: dict) -> tuple[str, str]:
    """
    Open candidate CTA links in a real browser tab, follow redirects, and copy
    the final URL from the browser. A winner is not allowed through without it.
    """
    for _score, candidate, label in rank_card_links(card)[:5]:
        tab = None
        try:
            tab = page.context.new_page()
            print(f"    ↗ VERIFY LANDING | {label[:45] or 'link'}", flush=True)
            try:
                tab.goto(candidate, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                # Some stores keep loading forever; the address bar can still be final.
                pass
            try:
                tab.wait_for_timeout(1800)
            except Exception:
                pass

            final_url = external_final_url(tab.url)
            if final_url:
                print(f"    ✅ LANDING VERIFIED | {final_url[:120]}", flush=True)
                return final_url, "Browser verified"

            # Sometimes the redirect page exposes the destination as a visible external anchor.
            try:
                links = tab.locator("a[href]").evaluate_all(
                    "els => els.map(a => a.href).filter(Boolean).slice(0, 50)"
                )
                for href in links:
                    final_url = external_final_url(href)
                    if final_url:
                        print(f"    ✅ LANDING VERIFIED | {final_url[:120]}", flush=True)
                        return final_url, "Browser verified"
            except Exception:
                pass
        except Exception as exc:
            print(f"    LANDING VERIFY WARNING | {str(exc)[:100]}", flush=True)
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
    print("WINNING PRODUCTS SCANNER V5", flush=True)
    print("META FILTER: ACTIVE + VIDEO + STARTED ON/BEFORE 14-DAY CUTOFF", flush=True)
    print(f"14-DAY CUTOFF: {cutoff}", flush=True)
    print("SORT: TOTAL IMPRESSIONS DESC", flush=True)
    print("LANDING URL: MANDATORY + VERIFIED IN A NEW BROWSER TAB", flush=True)
    print("SECOND CHECK: every card is parsed and <14 days is rejected", flush=True)
    print("============================================================", flush=True)
    v4.main()
