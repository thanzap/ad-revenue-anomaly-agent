"""Deterministic anomaly detection and root-cause decomposition.

Detection never involves the LLM. The agent only *explains* what this module
finds, using the drill-down functions below as tools.

Baseline: the median of the same weekday over the previous N weeks. Ad
revenue has a strong weekly cycle (weekend traffic and eCPMs differ), so
comparing Monday with last Monday beats a rolling 7-day mean. The spread is
the median absolute deviation (MAD) of those weeks, which a single past
outlier can't inflate the way it inflates a standard deviation.

A publisher-day is flagged when it moves by at least `min_pct` AND by at
least `min_z` robust standard deviations: the first filter drops tiny
publishers' noise, the second drops normally volatile publishers' swings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

MAD_TO_SIGMA = 1.4826


@dataclass
class Anomaly:
    date: str
    publisher: str
    metric: str
    actual: float
    baseline: float
    pct_change: float
    robust_z: float
    impact_eur: float
    direction: str

    def to_dict(self) -> dict:
        return asdict(self)


def _same_weekday_history(df: pd.DataFrame, day: date, weeks: int) -> pd.DataFrame:
    days = [day - timedelta(weeks=w) for w in range(1, weeks + 1)]
    return df[df["date"].isin(days)]


def daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["date", "publisher"], as_index=False)[
        ["impressions", "revenue_eur"]
    ].sum()


def detect(
    df: pd.DataFrame,
    day: date,
    weeks: int = 4,
    min_pct: float = 0.20,
    min_z: float = 3.0,
    metric: str = "revenue_eur",
) -> list[Anomaly]:
    """Publisher-level anomalies on `day`, largest € impact first."""
    totals = daily_totals(df)
    today = totals[totals["date"] == day].set_index("publisher")[metric]
    hist = _same_weekday_history(totals, day, weeks)

    found = []
    for pub, values in hist.groupby("publisher")[metric]:
        if pub not in today.index or len(values) < 3:
            continue
        baseline = float(np.median(values))
        mad = float(np.median(np.abs(values - baseline))) * MAD_TO_SIGMA
        sigma = max(
            mad, 0.02 * baseline, 1e-9
        )  # floor: very stable series shouldn't alert on noise
        actual = float(today[pub])
        pct = (actual - baseline) / baseline if baseline else 0.0
        z = (actual - baseline) / sigma
        if abs(pct) >= min_pct and abs(z) >= min_z:
            found.append(
                Anomaly(
                    date=day.isoformat(),
                    publisher=pub,
                    metric=metric,
                    actual=round(actual, 2),
                    baseline=round(baseline, 2),
                    pct_change=round(pct, 4),
                    robust_z=round(z, 2),
                    impact_eur=round(actual - baseline, 2),
                    direction="up" if actual > baseline else "down",
                )
            )
    return sorted(found, key=lambda a: abs(a.impact_eur), reverse=True)


def breakdown(
    df: pd.DataFrame, publisher: str, day: date, weeks: int = 4
) -> list[dict]:
    """Per demand source: actual vs same-weekday baseline, split into a
    volume effect (impressions) and a price effect (eCPM).

    revenue = impressions × eCPM / 1000, so
    Δrevenue ≈ Δimpressions × baseline_eCPM/1000  (volume effect)
             + actual_impressions × ΔeCPM/1000     (price effect)
    and the two terms sum exactly to the total change.
    """
    pub = df[df["publisher"] == publisher]
    today = pub[pub["date"] == day].set_index("demand_source")
    hist = _same_weekday_history(pub, day, weeks)
    base = hist.groupby("demand_source")[["impressions", "revenue_eur"]].median()

    rows = []
    for src in sorted(set(base.index) | set(today.index)):
        b_imp = float(base.loc[src, "impressions"]) if src in base.index else 0.0
        b_rev = float(base.loc[src, "revenue_eur"]) if src in base.index else 0.0
        present = src in today.index
        a_imp = float(today.loc[src, "impressions"]) if present else 0.0
        a_rev = float(today.loc[src, "revenue_eur"]) if present else 0.0
        b_ecpm = b_rev / b_imp * 1000 if b_imp else 0.0
        a_ecpm = a_rev / a_imp * 1000 if a_imp else 0.0
        volume_effect = (a_imp - b_imp) * b_ecpm / 1000
        rows.append(
            {
                "demand_source": src,
                "row_present": present,
                "revenue_actual": round(a_rev, 2),
                "revenue_baseline": round(b_rev, 2),
                "revenue_change": round(a_rev - b_rev, 2),
                "impressions_pct_change": round((a_imp - b_imp) / b_imp, 4)
                if b_imp
                else None,
                "ecpm_actual": round(a_ecpm, 3),
                "ecpm_baseline": round(b_ecpm, 3),
                "volume_effect_eur": round(volume_effect, 2),
                "price_effect_eur": round((a_rev - b_rev) - volume_effect, 2),
            }
        )
    return sorted(rows, key=lambda r: abs(r["revenue_change"]), reverse=True)


def completeness(df: pd.DataFrame, day: date, lookback_days: int = 14) -> list[dict]:
    """(publisher, demand source) pairs that reported every day of the lookback
    window but have no row on `day`: a pipeline/export gap, not a revenue drop."""
    window = df[
        (df["date"] < day) & (df["date"] >= day - timedelta(days=lookback_days))
    ]
    expected = window.groupby(["publisher", "demand_source"])["date"].nunique()
    expected = set(expected[expected == lookback_days].index)
    present = set(
        map(
            tuple,
            df[df["date"] == day][["publisher", "demand_source"]]
            .drop_duplicates()
            .values,
        )
    )
    return [{"publisher": p, "demand_source": s} for p, s in sorted(expected - present)]


def classify(anomaly: Anomaly, rows: list[dict], gaps: list[dict]) -> str:
    """Rule-based label used by the no-LLM report and as a check on the agent."""
    if any(g["publisher"] == anomaly.publisher for g in gaps):
        return "data_gap"
    change = sum(r["revenue_change"] for r in rows) or 1e-9
    top = rows[0] if rows else None
    if top and len(rows) > 1 and abs(top["revenue_change"]) / abs(change) >= 0.7:
        return (
            "single_source_outage"
            if anomaly.direction == "down"
            else "single_source_spike"
        )
    volume = sum(r["volume_effect_eur"] for r in rows)
    price = sum(r["price_effect_eur"] for r in rows)
    return "traffic_change" if abs(volume) >= abs(price) else "price_change"
