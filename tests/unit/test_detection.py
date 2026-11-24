from datetime import timedelta

import pytest

from anomaly_agent import data, detection

DAY = data.REPORT_DATE


@pytest.fixture(scope="module")
def df():
    return data.generate()


def test_finds_exactly_the_injected_anomalies(df):
    found = {a.publisher: a for a in detection.detect(df, DAY)}
    assert set(found) == {"daily-sports", "tech-reviews", "travel-mag"}
    assert found["tech-reviews"].direction == "up"
    assert found["daily-sports"].direction == "down"
    # sorted by absolute euro impact
    impacts = [abs(a.impact_eur) for a in detection.detect(df, DAY)]
    assert impacts == sorted(impacts, reverse=True)


def test_no_false_positives_on_normal_days(df):
    for back in range(1, 40):
        assert detection.detect(df, DAY - timedelta(days=back)) == []


def test_missing_rows_are_a_data_gap_not_an_anomaly(df):
    assert detection.completeness(df, DAY) == [
        {"publisher": "food-blog", "demand_source": "ssp_gamma"}
    ]
    assert detection.completeness(df, DAY - timedelta(days=1)) == []


def test_volume_and_price_effects_sum_to_the_revenue_change(df):
    for row in detection.breakdown(df, "travel-mag", DAY):
        assert row["volume_effect_eur"] + row["price_effect_eur"] == pytest.approx(
            row["revenue_change"], abs=0.02
        )


@pytest.mark.parametrize(
    "publisher,label",
    [
        ("daily-sports", "single_source_outage"),
        ("tech-reviews", "traffic_change"),
        ("travel-mag", "price_change"),
    ],
)
def test_classification(df, publisher, label):
    gaps = detection.completeness(df, DAY)
    (a,) = [x for x in detection.detect(df, DAY) if x.publisher == publisher]
    assert detection.classify(a, detection.breakdown(df, publisher, DAY), gaps) == label


def test_outage_points_at_the_right_source(df):
    top = detection.breakdown(df, "daily-sports", DAY)[0]
    assert top["demand_source"] == "ssp_beta"
    assert (
        top["price_effect_eur"] < 0
        and abs(top["volume_effect_eur"]) < abs(top["price_effect_eur"]) / 10
    )


def test_one_outlier_week_does_not_hide_the_next_anomaly():
    """MAD baseline: a past spike must not widen the band enough to mask today's drop."""
    df = data.generate()
    spike_day = DAY - timedelta(weeks=2)
    mask = (df["date"] == spike_day) & (df["publisher"] == "daily-sports")
    df.loc[mask, "revenue_eur"] *= 3
    assert "daily-sports" in {a.publisher for a in detection.detect(df, DAY)}
