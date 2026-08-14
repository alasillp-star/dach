from __future__ import annotations

import json
from pathlib import Path

import scanner as base
from meta_ads_collector import MetaAdsCollector, FilterConfig

COOKIE_PATH = Path("data/facebook_cookies.json")
_collector = None


def load_cookies():
    if not COOKIE_PATH.exists():
        return None
    try:
        data = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if k and v}
    except Exception as exc:
        print(f"COOKIE LOAD ERROR: {exc}", flush=True)
    return None


def get_collector():
    global _collector
    if _collector is None:
        cookies = load_cookies()
        if cookies:
            print("FACEBOOK SESSION: authenticated cookies loaded", flush=True)
        else:
            print("FACEBOOK SESSION: no login cookies found; run LOGIN_FACEBOOK.cmd", flush=True)
        _collector = MetaAdsCollector(
            rate_limit_delay=8.0,
            jitter=4.0,
            max_retries=3,
            timeout=40,
            cookies=cookies,
        )
        _collector.__enter__()
    return _collector


def reset_collector():
    global _collector
    if _collector is not None:
        try:
            _collector.__exit__(None, None, None)
        except Exception:
            pass
    _collector = None


def search_pair(keyword: str, country: str):
    filters = FilterConfig(
        media_type="VIDEO",
        languages=["ar"],
        has_video=True,
    )
    collector = get_collector()
    before_errors = int(collector.get_stats().get("errors", 0)) if hasattr(collector, "get_stats") else 0
    ads = list(collector.search(
        query=keyword,
        country=country,
        status="ACTIVE",
        max_results=min(base.MAX_RESULTS, 10),
        page_size=min(base.MAX_RESULTS, 10),
        filter_config=filters,
    ))
    after_errors = int(collector.get_stats().get("errors", 0)) if hasattr(collector, "get_stats") else before_errors
    if not ads and after_errors > before_errors:
        print("SESSION WARNING: Meta rejected this search; refreshing persistent session", flush=True)
        reset_collector()
    return ads


base.search_pair = search_pair

if __name__ == "__main__":
    try:
        base.main()
    finally:
        reset_collector()
