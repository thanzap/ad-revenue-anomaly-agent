"""Deterministic Markdown briefing: the no-LLM fallback, and the ground truth
the agent's output is evaluated against."""

from __future__ import annotations

from datetime import date

from anomaly_agent import data, detection

ACTIONS = {
    "single_source_outage": "Check {src} bidder errors, ads.txt lines and contract status; contact the partner.",
    "single_source_spike": "Verify {src} numbers against the partner UI before reporting the uplift.",
    "traffic_change": "Confirm the traffic source in analytics; check viewability and invalid traffic.",
    "price_change": "Review floor prices and demand-partner pacing; compare eCPMs across publishers.",
    "data_gap": "Re-run the ingestion for the missing source before trusting this day.",
}


def triage(day: date) -> dict:
    df = data.load()
    gaps = detection.completeness(df, day)
    items = []
    for a in detection.detect(df, day):
        rows = detection.breakdown(df, a.publisher, day)
        items.append(
            {"anomaly": a, "label": detection.classify(a, rows, gaps), "sources": rows}
        )
    return {"date": day.isoformat(), "gaps": gaps, "items": items}


def to_markdown(result: dict) -> str:
    items, gaps = result["items"], result["gaps"]
    lost = sum(i["anomaly"].impact_eur for i in items if i["anomaly"].impact_eur < 0)
    gained = sum(i["anomaly"].impact_eur for i in items if i["anomaly"].impact_eur > 0)
    lines = [f"# Revenue anomalies: {result['date']}", ""]
    if not items:
        lines.append("No revenue anomalies today.")
    else:
        lines.append(
            f"**{len(items)} anomalies vs same-weekday baseline: {lost:,.0f} € at risk, "
            f"{gained:+,.0f} € unexpected uplift.**"
        )
    for i in items:
        a, top = i["anomaly"], i["sources"][0]
        lines += [
            "",
            f"## {a.publisher}: {a.pct_change:+.1%} ({a.impact_eur:+,.0f} €), `{i['label']}`",
            f"- Revenue {a.actual:,.0f} € vs baseline {a.baseline:,.0f} € (robust z = {a.robust_z})",
            f"- Largest mover: **{top['demand_source']}** {top['revenue_change']:+,.0f} € "
            f"(volume {top['volume_effect_eur']:+,.0f} €, price {top['price_effect_eur']:+,.0f} €)",
            f"- Next action: {ACTIONS[i['label']].format(src=top['demand_source'])}",
        ]
    lines += ["", "## Data quality"]
    if gaps:
        lines += [
            f"- Missing rows: **{g['publisher']} / {g['demand_source']}**. {ACTIONS['data_gap']}"
            for g in gaps
        ]
    else:
        lines.append("- All expected publisher/source rows present.")
    return "\n".join(lines) + "\n"
