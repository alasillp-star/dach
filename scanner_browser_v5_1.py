from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote_plus

import scanner_browser as v4
import scanner_browser_v5 as v5

# Keep the true raw V4 browser scan function before V5's wrapper replaces it.
_raw_scan_once = v5._original_scan_once


def build_url_filtered(keyword: str, country: str) -> str:
    """Meta-side 14-day filter, but force EN UI so card parsing stays stable."""
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


def build_url_fallback(keyword: str, country: str) -> str:
    """Fallback search: no date URL parameter; V4 still rejects anything <14 days."""
    return (
        "https://www.facebook.com/ads/library/?"
        "active_status=active&ad_type=all&"
        f"country={country}&is_targeted_country=false&media_type=video&"
        f"q={quote_plus(keyword)}&search_type=keyword_unordered&locale=en_US&"
        "sort_data%5Bmode%5D=total_impressions&"
        "sort_data%5Bdirection%5D=desc"
    )


def extract_cards_robust(page):
    """
    Prefer card text markers, but also discover cards from Ad Library detail links.
    This makes card detection more tolerant of small DOM/layout changes.
    """
    return page.evaluate(
        """(maxCards) => {
          const picked = [];
          const seen = new Set();

          function pushCard(el, forcedId) {
            if (!el) return;
            let text = (el.innerText || '').trim();
            if (!text || text.length > 18000) return;

            let id = forcedId || '';
            const idMatch = text.match(/Library ID:\\s*(\\d+)/i);
            if (idMatch) id = idMatch[1];

            if (!id) {
              const idLink = el.querySelector('a[href*="/ads/library/"][href*="id="]');
              if (idLink) {
                try { id = new URL(idLink.href).searchParams.get('id') || ''; } catch (_) {}
              }
            }
            if (!id || seen.has(id)) return;

            // English UI is forced by URL. If the date marker is not in this
            // exact node, walk slightly upward to capture the full ad card.
            if (!text.includes('Started running on')) {
              let p = el.parentElement;
              for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
                const t = (p.innerText || '').trim();
                if (t.includes('Started running on') && t.length < 18000) {
                  el = p;
                  text = t;
                  break;
                }
              }
            }

            if (!text.includes('Started running on')) return;
            if (!/Library ID:/i.test(text)) text = `Library ID: ${id}\n${text}`;

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

            seen.add(id);
            picked.push({text, links, videos, mediaSrcs});
          }

          // Method 1: known text markers.
          for (const el of Array.from(document.querySelectorAll('div'))) {
            const text = (el.innerText || '').trim();
            if (!text.includes('Library ID:') || !text.includes('Started running on')) continue;
            if (text.length > 18000) continue;
            const childHasBoth = Array.from(el.children).some(c => {
              const t = (c.innerText || '').trim();
              return t.includes('Library ID:') && t.includes('Started running on');
            });
            if (!childHasBoth) pushCard(el, '');
            if (picked.length >= maxCards) return picked;
          }

          // Method 2: detail links containing an ad id, then climb to card container.
          const anchors = Array.from(document.querySelectorAll('a[href*="/ads/library/"][href*="id="]'));
          for (const a of anchors) {
            let id = '';
            try { id = new URL(a.href).searchParams.get('id') || ''; } catch (_) {}
            if (!id || seen.has(id)) continue;
            let el = a;
            for (let i = 0; i < 8 && el; i++, el = el.parentElement) {
              const t = (el.innerText || '').trim();
              if (t.includes('Started running on') && t.length < 18000) {
                pushCard(el, id);
                break;
              }
            }
            if (picked.length >= maxCards) break;
          }

          return picked;
        }""",
        v4.MAX_CARDS,
    )


def scan_raw_with_fallback(page, keyword: str, country: str):
    # First: native Meta 14-day filter.
    v4.build_url = build_url_filtered
    cards = _raw_scan_once(page, keyword, country)
    if cards:
        print(f"META-FILTERED CARDS: {len(cards)}", flush=True)
        return cards

    # Fallback: if Meta's URL date filter/UI yields zero, broaden the page search
    # but keep ACTIVE + VIDEO. normalize_card still enforces >=14 days strictly.
    print("META FILTER RETURNED 0 — FALLBACK SEARCH WITHOUT DATE URL FILTER", flush=True)
    v4.build_url = build_url_fallback
    cards = _raw_scan_once(page, keyword, country)
    v4.build_url = build_url_filtered
    print(f"FALLBACK VISIBLE CARDS: {len(cards)}", flush=True)
    return cards


# Apply V5.1 patches.
v4.build_url = build_url_filtered
v4.extract_cards = extract_cards_robust
v5._original_scan_once = scan_raw_with_fallback


if __name__ == "__main__":
    cutoff = (v4.utcnow() - timedelta(days=v4.MIN_DAYS)).date().isoformat()
    print("============================================================", flush=True)
    print("WINNING PRODUCTS SCANNER V5.1 — ARAB MARKETS", flush=True)
    print("FIX: META UI FORCED TO ENGLISH FOR STABLE CARD PARSING", flush=True)
    print("MARKETS: ARAB COUNTRIES ONLY — DZ EXCLUDED", flush=True)
    print("SEARCH: ARABIC SHORT KEYWORDS", flush=True)
    print("META: ACTIVE + VIDEO + 14-DAY CUTOFF FIRST", flush=True)
    print(f"14-DAY CUTOFF: {cutoff}", flush=True)
    print("FALLBACK: IF 0 CARDS, SEARCH WITHOUT DATE URL FILTER", flush=True)
    print("FINAL RULE: <14 DAYS IS ALWAYS REJECTED LOCALLY", flush=True)
    print("LANDING: MANDATORY + SALES CTA PRIORITY", flush=True)
    print("============================================================", flush=True)
    v4.main()
