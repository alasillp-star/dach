from __future__ import annotations

import csv
import math
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from meta_ads_collector import MetaAdsCollector, FilterConfig

# --------------------------- CONFIG ---------------------------
MIN_DAYS = int(os.getenv("MIN_DAYS", "14"))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30"))
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "20"))
RUN_SECONDS = int(os.getenv("RUN_SECONDS", "20400"))  # 5h40m
STATE_PUSH_SECONDS = int(os.getenv("STATE_PUSH_SECONDS", "600"))

DATA_DIR = Path("data")
SEED_DIR = Path("seed")
CSV_PATH = DATA_DIR / "winning_ads.csv"
STATE_PATH = DATA_DIR / "scanner_state.json"
LEARNED_PATH = DATA_DIR / "keywords_learned_ar.txt"
COUNTRIES_PATH = Path("countries_ar.txt")

HEADERS = [
    "ad_id", "country", "page_name", "started_on", "days_running",
    "impressions_upper", "score", "ad_text", "product_url", "video_url",
    "ad_library_url", "keyword", "date_found"
]

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
WORD_RE = re.compile(r"[\u0600-\u06FF]{2,}")
BLOCKED_HOSTS = {
    "facebook.com", "www.facebook.com", "m.facebook.com", "l.facebook.com",
    "instagram.com", "www.instagram.com", "messenger.com", "www.messenger.com",
    "fb.com", "www.fb.com", "fb.me"
}

STOP_WORDS = {
    "هذا", "هذه", "ذلك", "التي", "الذي", "على", "الى", "إلى", "من", "في",
    "عن", "مع", "لك", "لها", "له", "وهو", "وهي", "كما", "كل", "بعد", "قبل",
    "يمكن", "الآن", "اليوم", "عند", "عبر", "بدون", "حتى", "بين", "أو", "او",
    "ما", "لا", "لم", "لن", "قد", "تم", "معك", "لديك", "لدينا", "جدا", "جداً"
}

PRODUCT_SIGNALS = {
    "جهاز", "كريم", "سيروم", "شامبو", "فرشاة", "ماسك", "قناع", "زيت", "منظف",
    "حامل", "شاحن", "مصباح", "كشاف", "مقشر", "مدلك", "مكبر", "سماعات", "ساعة",
    "ميزان", "خلاط", "موزع", "مروحة", "مضخة", "لاصقات", "لصقات", "بلسم", "تونر",
    "بخاخ", "أداة", "اداة", "مقلاة", "قلاية", "مكنسة", "كاميرا", "نظارات"
}

COMMERCE_SIGNALS = {
    "اطلب", "أطلب", "اشتري", "اشتر", "شراء", "عرض", "خصم", "توصيل", "شحن",
    "الدفع", "الاستلام", "مجانا", "مجاناً", "الكمية", "محدودة", "السعر"
}

# --------------------------- HELPERS ---------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\s+", " ", line.strip())
        if line and not line.startswith("#"):
            out.append(line)
    return out


def load_keywords() -> list[str]:
    values: list[str] = []
    for path in sorted(SEED_DIR.glob("keywords_ar_*.txt")):
        values.extend(read_lines(path))
    values.extend(read_lines(LEARNED_PATH))
    seen = set()
    out = []
    for value in values:
        key = value.casefold()
        if ARABIC_RE.search(value) and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def load_countries() -> list[str]:
    # DZ intentionally absent from countries_ar.txt.
    return [x.upper() for x in read_lines(COUNTRIES_PATH) if x.upper() != "DZ"]


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"cursor": 0, "attempts": 0, "errors": 0}
    try:
        import json
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"cursor": 0, "attempts": 0, "errors": 0}


def save_state(state: dict) -> None:
    import json
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_start(value):
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def clean_text(parts) -> str:
    seen = set()
    out = []
    for part in parts:
        if not part:
            continue
        value = re.sub(r"\s+", " ", str(part)).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return " | ".join(out)


def unwrap_facebook_redirect(url: str) -> str:
    try:
        parsed = urlparse(url)
        h = parsed.netloc.lower().split(":")[0]
        if h in {"l.facebook.com", "lm.facebook.com"}:
            qs = parse_qs(parsed.query)
            if qs.get("u"):
                return qs["u"][0]
    except Exception:
        pass
    return url


def valid_product_url(url: str) -> str:
    if not url or not str(url).startswith(("http://", "https://")):
        return ""
    url = unwrap_facebook_redirect(str(url).strip())
    try:
        parsed = urlparse(url)
        h = parsed.netloc.lower().split(":")[0]
        if not h or h in BLOCKED_HOSTS or h.endswith(".facebook.com") or h.endswith(".instagram.com"):
            return ""
        if h.endswith(".dz"):
            return ""
        return url
    except Exception:
        return ""


def get_impressions_upper(ad) -> int:
    imp = getattr(ad, "impressions", None)
    if not imp:
        return 0
    for attr in ("upper_bound", "upper", "max"):
        value = getattr(imp, attr, None)
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    return 0


def winner_score(days: int, impressions: int) -> int:
    longevity = min(days, 365)
    reach = int(math.log10(impressions + 1) * 15) if impressions > 0 else 0
    return longevity + reach


def normalize_ad(ad, keyword: str, country: str):
    ad_id = str(getattr(ad, "id", "") or "").strip()
    if not ad_id:
        return None

    active = getattr(ad, "is_active", None)
    status = str(getattr(ad, "ad_status", "") or "").upper()
    if active is False or (status and "ACTIVE" not in status):
        return None

    started = parse_start(getattr(ad, "delivery_start_time", None))
    if not started:
        return None
    days = (utcnow() - started).days
    if days < MIN_DAYS:
        return None

    creatives = list(getattr(ad, "creatives", None) or [])
    if not creatives:
        return None

    video_url = ""
    product_url = ""
    text_parts = []
    for creative in creatives:
        text_parts.extend([
            getattr(creative, "body", None),
            getattr(creative, "title", None),
            getattr(creative, "description", None),
        ])
        if not video_url:
            v = getattr(creative, "video_url", None)
            if v and str(v).startswith("http"):
                video_url = str(v)
        if not product_url:
            product_url = valid_product_url(getattr(creative, "link_url", None))

    ad_text = clean_text(text_parts)
    # Meta's language filter is conservative; enforce Arabic ourselves too.
    if not ARABIC_RE.search(ad_text):
        return None
    if not video_url or not product_url:
        return None

    page = getattr(ad, "page", None)
    page_name = str(getattr(page, "name", "") or "")
    impressions = get_impressions_upper(ad)
    now = utcnow()

    return {
        "ad_id": ad_id,
        "country": country,
        "page_name": page_name,
        "started_on": started.date().isoformat(),
        "days_running": days,
        "impressions_upper": impressions,
        "score": winner_score(days, impressions),
        "ad_text": ad_text,
        "product_url": product_url,
        "video_url": video_url,
        "ad_library_url": f"https://www.facebook.com/ads/library/?id={ad_id}",
        "keyword": keyword,
        "date_found": now.isoformat(timespec="seconds"),
    }


def load_existing() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not CSV_PATH.exists():
        return rows
    try:
        with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("ad_id"):
                    rows[str(row["ad_id"])] = {h: row.get(h, "") for h in HEADERS}
    except Exception as exc:
        print("CSV LOAD ERROR:", exc, flush=True)
    return rows


def write_csv(rows: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    values = list(rows.values())
    values.sort(key=lambda r: (
        int(float(r.get("score") or 0)),
        str(r.get("date_found") or "")
    ), reverse=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(values)


def phrase_score(words: list[str]) -> int:
    joined = " ".join(words)
    score = len(words) * 2
    if any(signal in joined for signal in PRODUCT_SIGNALS):
        score += 12
    if any(signal in joined for signal in COMMERCE_SIGNALS):
        score += 7
    return score


def learn_from_text(text: str, existing_keywords: set[str], limit: int = 8) -> list[str]:
    words = [w for w in WORD_RE.findall(text) if w not in STOP_WORDS]
    candidates: dict[str, int] = {}
    for n in (2, 3, 4):
        for i in range(0, max(0, len(words) - n + 1)):
            phrase_words = words[i:i+n]
            phrase = " ".join(phrase_words)
            key = phrase.casefold()
            if key in existing_keywords:
                continue
            score = phrase_score(phrase_words)
            if score >= 16:
                candidates[phrase] = max(candidates.get(phrase, 0), score)
    ranked = sorted(candidates.items(), key=lambda x: (-x[1], len(x[0])))
    return [x[0] for x in ranked[:limit]]


def append_learned(phrases: list[str]) -> int:
    if not phrases:
        return 0
    LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEARNED_PATH.open("a", encoding="utf-8") as f:
        for phrase in phrases:
            f.write(phrase + "\n")
    return len(phrases)


def run_git(*args, check=False):
    return subprocess.run(["git", *args], text=True, capture_output=True, check=check)


def publish_to_github(message: str) -> bool:
    # Publishes results so Google Sheet IMPORTDATA can see them.
    paths = [str(CSV_PATH), str(STATE_PATH), str(LEARNED_PATH)]
    run_git("add", *paths)
    staged = run_git("diff", "--cached", "--quiet")
    if staged.returncode == 0:
        return True

    commit = run_git("commit", "-m", message)
    if commit.returncode != 0:
        print("GIT COMMIT ERROR:", commit.stderr, flush=True)
        return False

    for attempt in range(3):
        pull = run_git("pull", "--rebase", "origin", "main")
        if pull.returncode != 0:
            print("GIT PULL ERROR:", pull.stderr, flush=True)
            run_git("rebase", "--abort")
            return False
        push = run_git("push", "origin", "main")
        if push.returncode == 0:
            return True
        print("GIT PUSH RETRY:", push.stderr, flush=True)
        time.sleep(3 + attempt * 3)
    return False


def search_pair(keyword: str, country: str):
    filters = FilterConfig(
        media_type="VIDEO",
        languages=["ar"],
        has_video=True,
    )
    # A new client per search gets fresh public Ad Library session tokens.
    with MetaAdsCollector(rate_limit_delay=4.0, jitter=2.0, max_retries=3, timeout=30) as collector:
        return list(collector.search(
            query=keyword,
            country=country,
            status="ACTIVE",
            max_results=MAX_RESULTS,
            page_size=min(MAX_RESULTS, 20),
            filter_config=filters,
        ))


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEARNED_PATH.exists():
        LEARNED_PATH.write_text("# Auto-learned Arabic keywords\n", encoding="utf-8")

    countries = load_countries()
    if not countries:
        raise SystemExit("countries_ar.txt is empty")

    state = load_state()
    existing = load_existing()
    write_csv(existing)

    started_loop = time.monotonic()
    last_state_push = time.monotonic()
    consecutive_errors = 0

    while time.monotonic() - started_loop < RUN_SECONDS:
        loop_started = time.monotonic()
        keywords = load_keywords()
        if not keywords:
            raise SystemExit("No Arabic keywords found")

        cursor = int(state.get("cursor", 0))
        keyword = keywords[cursor % len(keywords)]
        country = countries[(cursor * 5) % len(countries)]
        state["cursor"] = cursor + 1
        state["attempts"] = int(state.get("attempts", 0)) + 1
        state["last_keyword"] = keyword
        state["last_country"] = country
        state["last_attempt"] = utcnow().isoformat(timespec="seconds")

        print(f"SEARCH #{state['attempts']} | {country} | {keyword}", flush=True)
        added_rows = 0
        learned_count = 0

        try:
            ads = search_pair(keyword, country)
            consecutive_errors = 0
            keyword_keys = {k.casefold() for k in keywords}
            for ad in ads:
                row = normalize_ad(ad, keyword, country)
                if not row or row["ad_id"] in existing:
                    continue
                existing[row["ad_id"]] = row
                added_rows += 1
                phrases = learn_from_text(row["ad_text"], keyword_keys)
                for phrase in phrases:
                    keyword_keys.add(phrase.casefold())
                learned_count += append_learned(phrases)
                print(
                    f"WINNER + {row['ad_id']} | {country} | {row['days_running']}d | {row['page_name']}",
                    flush=True,
                )
        except Exception as exc:
            consecutive_errors += 1
            state["errors"] = int(state.get("errors", 0)) + 1
            state["last_error"] = str(exc)[:500]
            print(f"SEARCH ERROR ({consecutive_errors}): {exc}", flush=True)

        state["total_ads"] = len(existing)
        state["added_last_attempt"] = added_rows
        state["learned_last_attempt"] = learned_count
        save_state(state)

        if added_rows or learned_count:
            write_csv(existing)
            publish_to_github(f"Arabic scanner: +{added_rows} winners")
            last_state_push = time.monotonic()
        elif time.monotonic() - last_state_push >= STATE_PUSH_SECONDS:
            publish_to_github("Arabic scanner heartbeat")
            last_state_push = time.monotonic()

        elapsed = time.monotonic() - loop_started
        # Try again at ~30s cadence when Meta answers quickly. If Meta rate-limits,
        # its retry/backoff is respected and we do not hammer the service.
        sleep_for = max(0.0, INTERVAL_SECONDS - elapsed)
        if consecutive_errors >= 3:
            sleep_for = max(sleep_for, min(300, 30 * consecutive_errors))
        if sleep_for:
            time.sleep(sleep_for)

    save_state(state)
    write_csv(existing)
    publish_to_github("Arabic scanner checkpoint")


if __name__ == "__main__":
    main()
