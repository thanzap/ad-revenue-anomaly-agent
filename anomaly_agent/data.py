"""Synthetic programmatic-ad revenue data with known, injected incidents.

Shape mirrors a typical publisher reporting table: one row per
(date, publisher, demand source) with impressions and revenue. The generator
is deterministic (seeded) so tests and evals can assert on exact incidents.

Injected incidents (all on or just before REPORT_DATE):

| publisher       | date        | what happened                                   | expected triage   |
|-----------------|-------------|-------------------------------------------------|-------------------|
| daily-sports    | REPORT_DATE | ssp_beta stops bidding (≈0 revenue)              | single_source_outage |
| tech-reviews    | REPORT_DATE | viral article: impressions ×1.8, eCPM flat      | traffic_change    |
| food-blog       | REPORT_DATE | ssp_gamma rows missing from the export          | data_gap          |
| travel-mag      | REPORT_DATE | eCPM −40 % on every source, impressions flat    | price_change      |
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

REPORT_DATE = date(2026, 11, 9)
HISTORY_DAYS = 70

PUBLISHERS = {
    # publisher: (daily impressions, base eCPM €)
    "daily-sports": (2_400_000, 1.10),
    "tech-reviews": (900_000, 1.65),
    "food-blog": (650_000, 0.95),
    "travel-mag": (480_000, 1.40),
    "local-news": (1_300_000, 0.80),
    "auto-world": (700_000, 1.25),
}
# demand source: share of impressions, eCPM multiplier
SOURCES = {
    "ssp_alpha": (0.35, 1.05),
    "ssp_beta": (0.30, 1.00),
    "ssp_gamma": (0.20, 0.90),
    "ad_exchange": (0.15, 1.10),
}
WEEKLY_TRAFFIC = [1.00, 1.02, 1.01, 1.00, 0.97, 0.85, 0.88]  # Mon..Sun
WEEKLY_ECPM = [0.98, 1.00, 1.01, 1.02, 1.04, 0.95, 0.93]

DATA_PATH_ENV = "ANOMALY_DATA_PATH"
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_revenue.csv"


def generate(
    report_date: date = REPORT_DATE, days: int = HISTORY_DAYS, seed: int = 7
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    start = report_date - timedelta(days=days - 1)
    for i in range(days):
        d = start + timedelta(days=i)
        trend = 1 + 0.0015 * i  # slow organic growth
        for pub, (imps, ecpm) in PUBLISHERS.items():
            for src, (share, mult) in SOURCES.items():
                vol = (
                    imps
                    * share
                    * WEEKLY_TRAFFIC[d.weekday()]
                    * trend
                    * rng.normal(1, 0.04)
                )
                price = ecpm * mult * WEEKLY_ECPM[d.weekday()] * rng.normal(1, 0.03)

                if d == report_date:
                    if pub == "daily-sports" and src == "ssp_beta":
                        price *= 0.02
                    if pub == "tech-reviews":
                        vol *= 1.8
                    if pub == "food-blog" and src == "ssp_gamma":
                        continue  # row missing from the export
                    if pub == "travel-mag":
                        price *= 0.60

                vol = int(max(vol, 0))
                rows.append(
                    {
                        "date": d,
                        "publisher": pub,
                        "demand_source": src,
                        "impressions": vol,
                        "revenue_eur": round(vol / 1000 * price, 2),
                    }
                )
    return pd.DataFrame(rows)


@lru_cache(maxsize=4)
def _load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


def load() -> pd.DataFrame:
    """The reporting table. In production this is a BigQuery query
    (see sql/detect_anomalies.sql); here a CSV, overridable via ANOMALY_DATA_PATH."""
    path = Path(os.environ.get(DATA_PATH_ENV, DEFAULT_PATH))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        generate().to_csv(path, index=False)
    return _load(str(path)).copy()


if __name__ == "__main__":
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    generate().to_csv(DEFAULT_PATH, index=False)
    print(f"wrote {DEFAULT_PATH}")
