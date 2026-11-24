"""ADK function tools: thin, typed wrappers over the deterministic detection code.

Each returns a JSON-serialisable dict with a `status` key, so the model always
gets a structured answer (including on bad input) instead of an exception.
"""

from __future__ import annotations

from datetime import date, timedelta

from anomaly_agent import data, detection


def _parse(day: str) -> date | None:
    try:
        return date.fromisoformat(day)
    except (TypeError, ValueError):
        return None


def _bad_date(day: str) -> dict:
    return {
        "status": "error",
        "message": f"'{day}' is not a date in YYYY-MM-DD format.",
    }


def list_anomalies(report_date: str) -> dict:
    """Lists publishers whose daily revenue deviates abnormally from the same weekday in previous weeks.

    Args:
        report_date: The day to check, formatted YYYY-MM-DD.

    Returns:
        dict with 'status' and 'anomalies' (largest euro impact first); each has
        publisher, actual, baseline, pct_change, robust_z, impact_eur and direction.
    """
    day = _parse(report_date)
    if day is None:
        return _bad_date(report_date)
    found = detection.detect(data.load(), day)
    return {
        "status": "success",
        "report_date": report_date,
        "anomalies": [a.to_dict() for a in found],
    }


def check_data_completeness(report_date: str) -> dict:
    """Finds publisher/demand-source pairs that normally report every day but have no data on this date.

    Missing rows mean a pipeline or export problem, not a real revenue change.

    Args:
        report_date: The day to check, formatted YYYY-MM-DD.

    Returns:
        dict with 'status' and 'missing' (list of publisher/demand_source pairs).
    """
    day = _parse(report_date)
    if day is None:
        return _bad_date(report_date)
    return {"status": "success", "missing": detection.completeness(data.load(), day)}


def get_revenue_breakdown(publisher: str, report_date: str) -> dict:
    """Breaks one publisher's revenue change down by demand source, into volume and price effects.

    Use it to find what drove an anomaly: a single demand source, a traffic
    (impressions) change, or a price (eCPM) change across sources.

    Args:
        publisher: Publisher id exactly as returned by list_anomalies.
        report_date: The day to analyse, formatted YYYY-MM-DD.

    Returns:
        dict with 'status' and 'sources': per demand source the actual and
        baseline revenue, impressions % change, eCPM actual/baseline, and the
        volume_effect_eur / price_effect_eur that sum to the revenue change.
    """
    day = _parse(report_date)
    if day is None:
        return _bad_date(report_date)
    df = data.load()
    if publisher not in set(df["publisher"]):
        return {"status": "error", "message": f"Unknown publisher '{publisher}'."}
    return {
        "status": "success",
        "publisher": publisher,
        "sources": detection.breakdown(df, publisher, day),
    }


def get_daily_trend(publisher: str, report_date: str, days: int) -> dict:
    """Returns a publisher's daily impressions, revenue and eCPM for the days up to report_date.

    Use it to tell a one-day blip from a change that started earlier.

    Args:
        publisher: Publisher id.
        report_date: Last day of the window, formatted YYYY-MM-DD.
        days: Number of days to return (1-60).

    Returns:
        dict with 'status' and 'series' (oldest first).
    """
    day = _parse(report_date)
    if day is None:
        return _bad_date(report_date)
    days = max(1, min(int(days), 60))
    totals = detection.daily_totals(data.load())
    pub = totals[
        (totals["publisher"] == publisher)
        & (totals["date"] > day - timedelta(days=days))
        & (totals["date"] <= day)
    ]
    series = [
        {
            "date": r.date.isoformat(),
            "impressions": int(r.impressions),
            "revenue_eur": round(r.revenue_eur, 2),
            "ecpm": round(r.revenue_eur / r.impressions * 1000, 3)
            if r.impressions
            else None,
        }
        for r in pub.sort_values("date").itertuples()
    ]
    return {"status": "success", "publisher": publisher, "series": series}


ALL_TOOLS = [
    list_anomalies,
    check_data_completeness,
    get_revenue_breakdown,
    get_daily_trend,
]
