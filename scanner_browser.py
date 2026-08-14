from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import scanner as base

PROFILE = Path('anonymous_meta_profile')
MIN_DAYS = int(os.getenv('MIN_DAYS', '14'))
INTERVAL_SECONDS = int(os.getenv('INTERVAL_SECONDS', '30'))
RUN_SECONDS = int(os.getenv('RUN_SECONDS', '20400'))
SCROLL_ROUNDS = int(os.getenv('SCROLL_ROUNDS', '4'))
MAX_CARDS = int(os.getenv('MAX_RESULTS', '20'))

MONTH_FORMATS = ['%b %d, %Y', '%B %d, %Y']
ARABIC_RE = re.compile(r'[\u0600-\u06FF]')


def utcnow():
    return datetime.now(timezone.utc)


def build_url(keyword: str, country: str) -> str:
    return (
        'https://www.facebook.com/ads/library/?'
        'active_status=active&ad_type=all&'
        f'country={country}&is_targeted_country=false&media_type=video&'
        f'q={quote_plus(keyword)}&search_type=keyword_unordered'
    )


def unwrap_external(url: str) -> str:
    if not url:
        return ''
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        if host in {'l.facebook.com', 'lm.facebook.com'}:
            qs = parse_qs(p.query)
            if qs.get('u'):
                url = unquote(qs['u'][0])
                p = urlparse(url)
                host = p.netloc.lower()
        blocked = ('facebook.com', 'instagram.com', 'messenger.com', 'fb.com')
        if any(host == b or host.endswith('.' + b) for b in blocked):
            return ''
        if host.endswith('.dz'):
            return ''
        if p.scheme in {'http', 'https'} and host:
            return url
    except Exception:
        pass
    return ''


def parse_started(text: str):
    m = re.search(r'Started running on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})', text, re.I)
    if not m:
        return None
    raw = m.group(1)
    for fmt in MONTH_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def extract_page_name(text: str) -> str:
    lines = [re.sub(r'\s+', ' ', x).strip() for x in text.splitlines() if x.strip()]
    banned = ('Library ID:', 'Started running on', 'Active', 'Sponsored', 'Platforms')
    for line in lines:
        if any(line.startswith(x) for x in banned):
            continue
        if len(line) <= 120:
            return line
    return ''


def extract_cards(page):
    return page.evaluate(
        '''(maxCards) => {
          const all = Array.from(document.querySelectorAll('div'));
          const picked = [];
          for (const el of all) {
            const text = (el.innerText || '').trim();
            if (!text.includes('Library ID:')) continue;
            if (!text.includes('Started running on')) continue;
            if (text.length > 12000) continue;
            const childHasBoth = Array.from(el.children).some(c => {
              const t = (c.innerText || '').trim();
              return t.includes('Library ID:') && t.includes('Started running on');
            });
            if (childHasBoth) continue;
            const links = Array.from(el.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean);
            const videos = Array.from(el.querySelectorAll('video')).map(v => ({
              src: v.currentSrc || v.src || '',
              poster: v.poster || ''
            }));
            picked.push({text, links, videos});
            if (picked.length >= maxCards) break;
          }
          return picked;
        }''',
        maxCards,
    )


def normalize_card(card: dict, keyword: str, country: str):
    text = re.sub(r'\s+', ' ', str(card.get('text') or '')).strip()
    if not text or not ARABIC_RE.search(text):
        return None

    m = re.search(r'Library ID:\s*(\d+)', text, re.I)
    if not m:
        return None
    ad_id = m.group(1)

    started = parse_started(text)
    if not started:
        return None
    days = (utcnow() - started).days
    if days < MIN_DAYS:
        return None

    product_url = ''
    for href in card.get('links') or []:
        candidate = unwrap_external(str(href))
        if candidate:
            product_url = candidate
            break
    if not product_url:
        return None

    video_url = ''
    for video in card.get('videos') or []:
        src = str((video or {}).get('src') or '')
        if src.startswith(('http://', 'https://')):
            video_url = src
            break

    page_name = extract_page_name(str(card.get('text') or ''))
    now = utcnow()
    score = min(days, 365)

    return {
        'ad_id': ad_id,
        'country': country,
        'page_name': page_name,
        'started_on': started.date().isoformat(),
        'days_running': days,
        'impressions_upper': 0,
        'score': score,
        'ad_text': text,
        'product_url': product_url,
        'video_url': video_url,
        'ad_library_url': f'https://www.facebook.com/ads/library/?id={ad_id}',
        'keyword': keyword,
        'date_found': now.isoformat(timespec='seconds'),
    }


def dismiss_dialogs(page):
    labels = [
        'Allow all cookies', 'Decline optional cookies', 'Only allow essential cookies',
        'Accept All Cookies', 'Reject optional cookies', 'Close'
    ]
    for label in labels:
        try:
            btn = page.get_by_role('button', name=label, exact=False)
            if btn.count() > 0:
                btn.first.click(timeout=1500)
                time.sleep(1)
        except Exception:
            pass


def detect_block(page):
    try:
        txt = page.locator('body').inner_text(timeout=3000).lower()
    except Exception:
        return ''
    signals = ['security check', 'confirm you are human', 'captcha', 'temporarily blocked']
    for s in signals:
        if s in txt:
            return s
    return ''


def scan_once(page, keyword: str, country: str):
    url = build_url(keyword, country)
    print(f'BROWSER SEARCH | {country} | {keyword}', flush=True)
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
    except PlaywrightTimeoutError:
        print('PAGE WARNING: initial load timed out; continuing with rendered page', flush=True)

    dismiss_dialogs(page)
    block = detect_block(page)
    if block:
        print(f'BROWSER BLOCKED: Meta displayed {block}; no bypass attempted', flush=True)
        return []

    try:
        page.wait_for_timeout(5000)
        for _ in range(SCROLL_ROUNDS):
            page.mouse.wheel(0, 2200)
            page.wait_for_timeout(1800)
    except Exception:
        pass

    cards = extract_cards(page)
    print(f'VISIBLE AD CARDS: {len(cards)}', flush=True)
    return cards


def main():
    PROFILE.mkdir(parents=True, exist_ok=True)
    state = base.load_state()
    existing = base.load_existing()
    base.write_csv(existing)
    countries = base.load_countries()
    if not countries:
        raise SystemExit('No Arabic countries configured')

    started_loop = time.monotonic()

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE),
                channel='chrome',
                headless=False,
                locale='en-US',
                viewport={'width': 1280, 'height': 900},
                args=['--disable-notifications'],
            )
        except Exception as exc:
            raise SystemExit(f'Could not launch Google Chrome with Playwright: {exc}')

        page = context.pages[0] if context.pages else context.new_page()
        print('META MODE: anonymous real Chrome browser - NO Facebook login used', flush=True)

        while time.monotonic() - started_loop < RUN_SECONDS:
            loop_started = time.monotonic()
            keywords = base.load_keywords()
            if not keywords:
                raise SystemExit('No Arabic keywords found')

            cursor = int(state.get('cursor', 0))
            keyword = keywords[cursor % len(keywords)]
            country = countries[(cursor * 5) % len(countries)]
            state['cursor'] = cursor + 1
            state['attempts'] = int(state.get('attempts', 0)) + 1
            state['last_keyword'] = keyword
            state['last_country'] = country
            state['last_attempt'] = utcnow().isoformat(timespec='seconds')

            added = 0
            learned = 0
            try:
                cards = scan_once(page, keyword, country)
                keyword_keys = {k.casefold() for k in keywords}
                for card in cards:
                    row = normalize_card(card, keyword, country)
                    if not row or row['ad_id'] in existing:
                        continue
                    existing[row['ad_id']] = row
                    added += 1
                    phrases = base.learn_from_text(row['ad_text'], keyword_keys)
                    for phrase in phrases:
                        keyword_keys.add(phrase.casefold())
                    learned += base.append_learned(phrases)

                if added:
                    base.write_csv(existing)
                    state['added_last_run'] = added
                    state['total_ads'] = len(existing)
                    state['learned_last_run'] = learned
                    base.save_state(state)
                    base.publish_to_github(f'Add {added} anonymous browser winners')
                    print(f'WINNERS: +{added} | TOTAL: {len(existing)} | LEARNED: {learned}', flush=True)
                else:
                    state['added_last_run'] = 0
                    state['total_ads'] = len(existing)
                    base.save_state(state)
                    print('WINNERS: +0', flush=True)
            except Exception as exc:
                state['errors'] = int(state.get('errors', 0)) + 1
                state['last_error'] = str(exc)
                base.save_state(state)
                print(f'BROWSER SEARCH ERROR: {exc}', flush=True)

            elapsed = time.monotonic() - loop_started
            wait_for = max(5, INTERVAL_SECONDS - int(elapsed))
            print(f'NEXT SEARCH IN {wait_for}s', flush=True)
            time.sleep(wait_for)

        try:
            context.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
