import pytest

from anomaly_agent import data, report, tools
from anomaly_agent.agent import INSTRUCTION, root_agent

DAY = data.REPORT_DATE.isoformat()


@pytest.fixture(autouse=True)
def sample_data(tmp_path, monkeypatch):
    path = tmp_path / "revenue.csv"
    data.generate().to_csv(path, index=False)
    monkeypatch.setenv(data.DATA_PATH_ENV, str(path))


def test_tools_return_structured_results():
    anomalies = tools.list_anomalies(DAY)
    assert anomalies["status"] == "success" and len(anomalies["anomalies"]) == 3
    assert tools.check_data_completeness(DAY)["missing"][0]["publisher"] == "food-blog"
    assert (
        tools.get_revenue_breakdown("daily-sports", DAY)["sources"][0]["demand_source"]
        == "ssp_beta"
    )
    series = tools.get_daily_trend("travel-mag", DAY, 14)["series"]
    assert len(series) == 14 and series[-1]["date"] == DAY


def test_tools_report_errors_instead_of_raising():
    assert tools.list_anomalies("yesterday")["status"] == "error"
    assert tools.get_revenue_breakdown("no-such-pub", DAY)["status"] == "error"
    assert len(tools.get_daily_trend("travel-mag", DAY, 999)["series"]) == 60  # clamped


def test_agent_has_every_tool_and_its_instruction_names_them():
    names = {t.__name__ for t in root_agent.tools}
    assert names == {
        "list_anomalies",
        "check_data_completeness",
        "get_revenue_breakdown",
        "get_daily_trend",
    }
    assert all(n in INSTRUCTION for n in names)


def test_markdown_report():
    md = report.to_markdown(report.triage(data.REPORT_DATE))
    assert "3 anomalies" in md
    assert "`single_source_outage`" in md and "ssp_beta" in md
    assert "food-blog / ssp_gamma" in md
    # biggest impact listed first
    assert md.index("tech-reviews") < md.index("daily-sports") < md.index("travel-mag")
