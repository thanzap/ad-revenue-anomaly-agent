"""Revenue-anomaly triage agent (Google ADK).

Detection is deterministic (detection.py). The agent investigates each
finding with drill-down tools and writes the briefing an ad-ops team reads in
the morning: what moved, why, and what to do. It is told never to state a
number it didn't get from a tool.
"""

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from anomaly_agent.tools import ALL_TOOLS

MODEL = "gemini-3.8-flash"

INSTRUCTION = """\
You are the revenue-operations analyst for a programmatic advertising network.
Every morning you triage yesterday's revenue anomalies and brief the ad-ops team.

Procedure for the date you are given:
1. Call check_data_completeness. Missing rows are a DATA GAP: report them first,
   and do not treat the matching revenue drop as a real business change.
2. Call list_anomalies. If there are none, say so in one line.
3. For EVERY anomaly call get_revenue_breakdown, and call get_daily_trend
   (14 days) when you need to know whether it started before that day.
4. Classify each anomaly as exactly one of:
   - single_source_outage / single_source_spike: one demand source explains ≥70% of the change
   - traffic_change: the volume effect (impressions) dominates
   - price_change: the price effect (eCPM) dominates across sources
   - data_gap: missing rows, see step 1

Write the briefing in Markdown:
- A one-line headline with the total € impact.
- One section per anomaly, largest impact first: classification, the evidence
  (cite the specific source, % change and € amounts from the tools), and one
  concrete next action (e.g. "check ssp_beta bidder errors / contract status",
  "confirm traffic source in analytics", "review floor prices with demand partners").
- A "Data quality" section for gaps.

Rules: use only numbers returned by tools; round € to whole euros and % to one
decimal; if a tool returns status=error, say what failed instead of guessing.
"""

root_agent = Agent(
    # Keep in sync with create_params.root_agent_name in agents-cli-manifest.yaml.
    name="anomaly_triage_agent",
    model=Gemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=3)),
    description="Investigates daily ad-revenue anomalies and writes an ad-ops briefing.",
    instruction=INSTRUCTION,
    tools=ALL_TOOLS,
    generate_content_config=types.GenerateContentConfig(temperature=0.1),
)

app = App(root_agent=root_agent, name="anomaly_agent")
