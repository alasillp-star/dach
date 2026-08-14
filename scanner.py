from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

MIN_DAYS = int(os.getenv("MIN_DAYS", "14"))
PAIRS_PER_RUN = int(os.getenv("PAIRS_PER_RUN", "12"))
MAX_RESULTS_PER_PAIR = int(os.getenv("MAX_RESULTS_PER_PAIR", "40"))

DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "winning_ads.csv"
STATE_PATH = DATA_DIR / "scanner_state.json"
KEYWORDS_PATH = Path("keywords.txt")
COUNTRIES_PATH = Path("countries.txt")

HEADERS = [
    "ad_id", "country", "page_name", "started_on", "days_running",
    "ad_text", "product_url", "video_url", "ad_library_url",
    "keyword", "date_found"
]

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
BLOCKED_HOSTS = {
    "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com",
    "fb.com", "www.fb.com", "messenger.com", "www.messenger.com"
}


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"cursor": 0}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"cursor": 0}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def flatten(obj, prefix="") -> list[tuple[str, object]]:
    rows = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            rows.extend(flatten(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            rows.extend(flatten(v, f"{prefix}[{i}]"))
    else:
        rows.append((prefix.lower(), obj))
    return rows


def first_value(flat: list[tuple[str, object]], hints: list[str]):
    for hint in hints:
        h = hint.lower()
        for key, value in flat:
            if h in key and value not in (None, "", [], {}):
                return value
    return None


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def clean_url(url: str) -> str:
    return str(url).rstrip(".,);]}>\"'")


def host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""


def extract_urls(obj) -> list[str]:
    urls = []
    for key, value in flatten(obj):
        if isinstance(value, str):
            if value.startswith("http://") or value.startswith("https://"):
                urls.append(clean_url(value))
            urls.extend(clean_url(x) for x in URL_RE.findall(value))
    return list(dict.fromkeys(urls))


def choose_product_url(obj) -> str:
    flat = flatten(obj)
    preferred = [
        "link_url", "destination_url", "landing", "website", "cta_url",
        "caption", "link_caption"
    ]
    for hint in preferred:
        for key, value in flat:
            if hint in key and isinstance(value, str) and value.startswith("http"):
                u = clean_url(value)
                if host(u) not in BLOCKED_HOSTS and ".facebook." not in host(u):
                    return u
    for u in extract_urls(obj):
        h = host(u)
        if h and h not in BLOCKED_HOSTS and ".facebook." not in h and ".instagram." not in h:
            return u
    return ""


def choose_video_url(obj) -> str:
    flat = flatten(obj)
    for key, value in flat:
        if isinstance(value, str) and value.startswith("http"):
            lk = key.lower()
            lv = value.lower()
            if "video" in lk or ".mp4" in lv or ".m3u8" in lv:
                return clean_url(value)
    return ""


def unwrap_ads(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("ads", "results", "data", "items"):
        v = data.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            nested = unwrap_ads(v)
            if nested:
                return nested
    # collector JSON metadata envelope can contain a nested list deeper down
    for v in data.values():
        if isinstance(v, (dict, list)):
            nested = unwrap_ads(v)
            if nested:
                return nested
    return []


def run_pair(keyword: str, country: str) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out = tmp.name
    cmd = [
        "meta-ads-collector",
        "-q", keyword,
        "-c", country,
        "-s", "active",
        "--has-video",
        "--sort-by", "impressions",
        "-n", str(MAX_RESULTS_PER_PAIR),
        "-o", out,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=240)
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        return unwrap_ads(data)
    except Exception as exc:
        print(f"PAIR ERROR {country} / {keyword}: {exc}")
        return []
    finally:
        try:
            Path(out).unlink(missing_ok=True)
        except Exception:
            pass


def normalize_ad(ad: dict, keyword: str, country: str):
    flat = flatten(ad)

    ad_id = first_value(flat, ["ad_archive_id", ".id", "ad.id", "archive_id"])
    if not ad_id:
        return None
    ad_id = str(ad_id)

    start_raw = first_value(flat, ["start_date", "started_on", "start_time", "delivery_start"])
    started = parse_date(start_raw)
    if not started:
        return None

    now = datetime.now(timezone.utc)
    days = (now - started).days
    if days < MIN_DAYS:
        return None

    page_name = first_value(flat, ["page.name", "page_name", "advertiser_name"]) or ""
    ad_text = first_value(flat, ["body_text", "primary_text", "creative.body", "ad_text", "body"]) or ""

    product_url = choose_product_url(ad)
    video_url = choose_video_url(ad)
    if not product_url or not video_url:
        return None

    ad_library_url = f"https://www.facebook.com/ads/library/?id={ad_id}"

    return {
        "ad_id": ad_id,
        "country": country,
        "page_name": str(page_name),
        "started_on": started.date().isoformat(),
        "days_running": days,
        "ad_text": re.sub(r"\s+", " ", str(ad_text)).strip(),
        "product_url": product_url,
        "video_url": video_url,
        "ad_library_url": ad_library_url,
        "keyword": keyword,
        "date_found": now.isoformat(timespec="seconds"),
    }


def load_existing() -> dict[str, dict]:
    if not CSV_PATH.exists():
        return {}
    rows = {}
    try:
        with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("ad_id"):
                    rows[row["ad_id"]] = row
    except Exception:
        pass
    return rows


def write_csv(rows: dict[str, dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    values = list(rows.values())
    values.sort(key=lambda r: int(r.get("days_running") or 0), reverse=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(values)


def main():
    keywords = read_lines(KEYWORDS_PATH)
    countries = [c.upper() for c in read_lines(COUNTRIES_PATH) if c.upper() != "DZ"]
    if not keywords or not countries:
        raise SystemExit("keywords.txt or countries.txt is empty")

    pairs = [(c, k) for c in countries for k in keywords]
    state = load_state()
    cursor = int(state.get("cursor", 0)) % len(pairs)
    selected = [pairs[(cursor + i) % len(pairs)] for i in range(min(PAIRS_PER_RUN, len(pairs)))]

    existing = load_existing()
    added = 0
    for country, keyword in selected:
        print(f"SCAN {country}: {keyword}")
        for raw in run_pair(keyword, country):
            row = normalize_ad(raw, keyword, country)
            if row and row["ad_id"] not in existing:
                existing[row["ad_id"]] = row
                added += 1

    write_csv(existing)
    state["cursor"] = (cursor + len(selected)) % len(pairs)
    state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["last_pairs"] = selected
    state["total_ads"] = len(existing)
    state["added_last_run"] = added
    save_state(state)
    print(f"DONE: +{added} new winners, {len(existing)} total")


if __name__ == "__main__":
    main()
