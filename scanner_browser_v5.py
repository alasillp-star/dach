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
    "رموش", "حواجب", "شفايف", "وجه", "أظافر", "مساج", "راحة", "نوم",
]

# Strong sales CTAs first. These are link/button labels, not search keywords.
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
    """Return a real external destination URL and reject Meta/internal/DZ links."""
    try:
        current = str(url or "").strip()
        if not current.startswith(("http://", "https://")):
            return ""

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


def cta_score(label: str) -> int:
    low = re.sub(r"\s+", " ", str(label or "")).strip().casefold()
    if any(x in low for x in SALES_CTA):
        return 200
    if any(x in low for x in SOFT_CTA):
        return 50
    return 0


def extract_ad_id(card: dict) -> str:
    text = str(card.get("text") or "")
    m = re.search(r"Library ID:\s*(\d+)", text, re.I)
    return m.group(1) if m else ""


def rank_card_links(card: dict):
    """Fallback only. Real CTA clicking is attempted first."""
    ranked = []
    seen = set()
    for link in card.get("links") or []:
        link = link or {}
        label = re.sub(r"\s+", " ", str(link.get("text") or "")).strip()
        for raw in (link.get("lynx"), link.get("href"), link.get("rawHref")):
            raw = str(raw or "").strip()
            if not raw.startswith(("http://", "https://")) or raw in seen:
                continue
            seen.add(raw)
            score = cta_score(label)
            low = raw.casefold()
            if "l.facebook.com" in low or "lm.facebook.com" in low:
                score += 60
            if "facebook.com/ads/library" in low:
                score -= 300
            if "facebook.com" not in low:
                score += 30
            ranked.append((score, raw, label))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def mark_real_cta(page, ad_id: str, token: str):
    """Find the actual clickable CTA node inside the exact ad card and mark it."""
    if not ad_id:
        return {"found": False}

    return page.evaluate(
        """(cfg) => {
          const needle = 'Library ID: ' + cfg.adId;
          const sales = cfg.sales.map(x => x.toLowerCase());
          const soft = cfg.soft.map(x => x.toLowerCase());

          const textOf = (el) => ((el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '') + '').trim();
          const norm = (s) => (s || '').toLowerCase().replace(/\s+/g, ' ').trim();
          const scoreNode = (el) => {
            const label = norm(textOf(el));
            let score = 0;
            if (sales.some(x => label.includes(x))) score += 1000;
            else if (soft.some(x => label.includes(x))) score += 200;
            if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') score += 80;
            if (el.tagName === 'A') score += 40;
            const href = el.href || el.getAttribute('href') || el.getAttribute('data-lynx-uri') || '';
            if (href && !href.includes('facebook.com/ads/library')) score += 60;
            return {score, label, href};
          };

          let candidates = Array.from(document.querySelectorAll('div')).filter(el => {
            const t = (el.innerText || '').trim();
            return t.includes(needle) && t.length < 22000;
          });
          candidates.sort((a,b) => (a.innerText || '').length - (b.innerText || '').length);

          let best = null;
          let bestMeta = null;
          for (const card of candidates) {
            const nodes = Array.from(card.querySelectorAll('a,button,[role="button"]'));
            for (const node of nodes) {
              const meta = scoreNode(node);
              if (meta.score <= 0) continue;
              if (!bestMeta || meta.score > bestMeta.score) {
                best = node;
                bestMeta = meta;
              }
            }
            if (bestMeta && bestMeta.score >= 1000) break;
          }

          if (!best || !bestMeta || bestMeta.score < 200) return {found:false};
          best.setAttribute('data-scanner-cta', cfg.token);
          try { best.scrollIntoView({block:'center', inline:'center'}); } catch (_) {}
          return {
            found: true,
            label: bestMeta.label,
            href: bestMeta.href,
            tag: best.tagName || '',
            score: bestMeta.score
          };
        }""",
        {
            "adId": ad_id,
            "token": token,
            "sales": list(SALES_CTA),
            "soft": list(SOFT_CTA),
        },
    )


def click_real_cta_and_capture(page, card: dict) -> tuple[str, str]:
    """
    Click the REAL CTA button/link inside the ad card. Capture landing URL from:
    popup/new tab, same-tab navigation, navigation requests, then href fallback.
    """
    ad_id = extract_ad_id(card)
    if not ad_id:
        return "", "no_ad_id"

    token = f"scancta-{ad_id}"
    info = mark_real_cta(page, ad_id, token)
    if not info or not info.get("found"):
        print(f"    ❌ CTA NOT FOUND IN DOM | Ad {ad_id}", flush=True)
        return "", "cta_not_found"

    label = str(info.get("label") or "CTA")
    href_fallback = external_final_url(str(info.get("href") or ""))
    print(f"    🖱 CLICK REAL CTA | {label[:70]}", flush=True)

    context = page.context
    main_url = page.url
    pages_before = list(context.pages)
    captured_requests = []

    def on_request(req):
        try:
            if req.is_navigation_request():
                u = external_final_url(req.url)
                if u:
                    captured_requests.append(u)
        except Exception:
            pass

    try:
        page.on("request", on_request)
    except Exception:
        pass

    new_pages = []
    try:
        locator = page.locator(f'[data-scanner-cta="{token}"]').first
        try:
            locator.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

        try:
            locator.click(timeout=8000)
        except Exception:
            # If an overlay blocks a visible CTA, force only the ordinary click itself.
            locator.click(timeout=5000, force=True)

        try:
            page.wait_for_timeout(2600)
        except Exception:
            pass

        new_pages = [p for p in context.pages if p not in pages_before]

        # 1) Popup/new tab final URL.
        for popup in new_pages:
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=7000)
            except Exception:
                pass
            try:
                popup.wait_for_timeout(1200)
            except Exception:
                pass
            final_url = external_final_url(popup.url)
            if final_url:
                print(f"    ✅ LANDING FROM NEW TAB | {final_url[:150]}", flush=True)
                return final_url, "Clicked CTA - new tab"

            # If popup has not fully loaded, inspect its visible outbound links.
            try:
                hrefs = popup.locator("a[href]").evaluate_all(
                    "els => els.map(a => a.href).filter(Boolean).slice(0,100)"
                )
                for href in hrefs:
                    final_url = external_final_url(href)
                    if final_url:
                        print(f"    ✅ LANDING FROM POPUP LINK | {final_url[:150]}", flush=True)
                        return final_url, "Clicked CTA - popup link"
            except Exception:
                pass

        # 2) Same-tab navigation.
        same_tab = external_final_url(page.url)
        if same_tab:
            print(f"    ✅ LANDING FROM SAME TAB | {same_tab[:150]}", flush=True)
            return same_tab, "Clicked CTA - same tab"

        # 3) Browser navigation request captured even if destination fails to render.
        if captured_requests:
            final_url = captured_requests[-1]
            print(f"    ✅ LANDING FROM NAV REQUEST | {final_url[:150]}", flush=True)
            return final_url, "Clicked CTA - navigation request"

        # 4) CTA href/meta redirect fallback after we already attempted the real click.
        if href_fallback:
            print(f"    ✅ LANDING FROM CTA HREF | {href_fallback[:150]}", flush=True)
            return href_fallback, "Clicked CTA - href fallback"

        print(f"    ❌ CTA CLICKED BUT NO EXTERNAL URL | Ad {ad_id}", flush=True)
        return "", "cta_click_no_external_url"

    except Exception as exc:
        if href_fallback:
            print(f"    ⚠ CLICK ERROR, USING CTA HREF | {href_fallback[:150]}", flush=True)
            return href_fallback, "CTA href fallback after click error"
        print(f"    ❌ CTA CLICK ERROR | {str(exc)[:140]}", flush=True)
        return "", "cta_click_error"

    finally:
        try:
            page.remove_listener("request", on_request)
        except Exception:
            pass
        for popup in new_pages:
            try:
                popup.close()
            except Exception:
                pass
        # If CTA took the main Ad Library tab away, restore the search page.
        try:
            if external_final_url(page.url):
                page.goto(main_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
        except Exception:
            pass


def verify_landing_in_new_tab(page, card: dict) -> tuple[str, str]:
    # Primary path: click the actual visible CTA button inside the exact ad card.
    url, source = click_real_cta_and_capture(page, card)
    if url:
        return url, source

    # Secondary path: old serialized-link fallback, only after a real CTA click attempt.
    for _score, candidate, label in rank_card_links(card)[:5]:
        direct = external_final_url(candidate)
        if direct:
            print(f"    ✅ FALLBACK LANDING | {label[:45] or 'link'} | {direct[:140]}", flush=True)
            return direct, "Serialized link fallback"

    return "", source


def scan_once_with_verified_landings(page, keyword: str, country: str):
    cards = _original_scan_once(page, keyword, country)
    if not cards:
        return cards

    verified = 0
    for index, card in enumerate(cards, start=1):
        ad_id = extract_ad_id(card) or "?"
        print(f"  CARD {index}/{len(cards)} | Ad {ad_id}", flush=True)
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
    print("CTA ENGINE: REAL DOM BUTTON CLICK + POPUP/NAVIGATION CAPTURE", flush=True)
    print("CTA PRIORITY: SHOP NOW / BUY NOW / ORDER NOW / اشتري / اطلب / تسوق", flush=True)
    print("META FILTER: ACTIVE + VIDEO + STARTED ON/BEFORE 14-DAY CUTOFF", flush=True)
    print(f"14-DAY CUTOFF: {cutoff}", flush=True)
    print("LANDING URL: MANDATORY", flush=True)
    print("NO CAPTCHA / LOGIN / ANTI-BOT BYPASS", flush=True)
    print("============================================================", flush=True)
    v4.main()
