from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from meta_ads_collector import MetaAdsCollector

MIN_DAYS = 14
PAIRS_PER_RUN = 10
MAX_RESULTS_PER_PAIR = 40
DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "winning_ads.csv"
STATE_PATH = DATA_DIR / "scanner_state.json"
KEYWORDS_PATH = Path("keywords.txt")

# Broad e-commerce markets. Algeria is intentionally excluded.