"""Daily run: `python -m anomaly_agent.cli --date 2026-11-09 [--no-llm]`.

With --no-llm the deterministic report is printed (no credentials needed).
Otherwise the ADK agent investigates and writes the briefing.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from anomaly_agent import data, report


async def run_agent(day: date) -> str:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from anomaly_agent.agent import app

    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=app.name, user_id="scheduler"
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text=f"Triage revenue anomalies for {day.isoformat()}.")],
    )
    final = ""
    async for event in runner.run_async(
        user_id="scheduler", session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", default=data.REPORT_DATE.isoformat(), help="YYYY-MM-DD"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="deterministic report only"
    )
    args = parser.parse_args()
    day = date.fromisoformat(args.date)
    if args.no_llm:
        print(report.to_markdown(report.triage(day)))
    else:
        print(asyncio.run(run_agent(day)))


if __name__ == "__main__":
    main()
