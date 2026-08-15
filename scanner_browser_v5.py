from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote_plus

import scanner_browser as v4


def build_url(keyword: str, country: str) -> str:
    # Winner logic: an ACTIVE VIDEO ad must have started no later than
    # today - MIN_DAYS. Meta applies this filter server-side/UI-side first,
    # and scanner_browser still verifies the parsed start date afterwards.
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


# Patch the working browser engine instead of duplicating it.
v4.build_url = build_url


if __name__ == "__main__":
    cutoff = (v4.utcnow() - timedelta(days=v4.MIN_DAYS)).date().isoformat()
    print("META NATIVE FILTER: ACTIVE + VIDEO + STARTED >=14 DAYS AGO", flush=True)
    print(f"META START DATE MAX: {cutoff}", flush=True)
    print("META SORT: TOTAL IMPRESSIONS DESC", flush=True)
    print("SECOND CHECK: scanner rejects anything under 14 days after parsing the card", flush=True)
    v4.main()
