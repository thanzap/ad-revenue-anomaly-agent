-- Publisher-level revenue anomalies for @report_date (BigQuery Standard SQL).
-- Same logic as anomaly_agent/detection.py: same-weekday median baseline over
-- the previous 4 weeks, robust spread = 1.4826 × MAD (floored at 2 % of the
-- baseline), flag when |Δ%| ≥ 20 % AND |robust z| ≥ 3.
--
-- Expects `revenue_daily` partitioned on `date`; the IN-list below prunes the
-- scan to 5 partitions regardless of table size.

DECLARE report_date DATE DEFAULT @report_date;

WITH daily AS (
  SELECT date, publisher, SUM(revenue_eur) AS revenue
  FROM `${project}.${dataset}.revenue_daily`
  WHERE date IN UNNEST(GENERATE_DATE_ARRAY(DATE_SUB(report_date, INTERVAL 28 DAY), report_date, INTERVAL 7 DAY))
  GROUP BY date, publisher
),
history AS (
  SELECT publisher, revenue FROM daily WHERE date < report_date
),
baseline AS (
  SELECT publisher, APPROX_QUANTILES(revenue, 2)[OFFSET(1)] AS median_rev, COUNT(*) AS weeks
  FROM history GROUP BY publisher
),
spread AS (
  SELECT h.publisher, APPROX_QUANTILES(ABS(h.revenue - b.median_rev), 2)[OFFSET(1)] * 1.4826 AS robust_sd
  FROM history h JOIN baseline b USING (publisher)
  GROUP BY h.publisher
)
SELECT
  report_date AS date,
  t.publisher,
  ROUND(t.revenue, 2) AS actual,
  ROUND(b.median_rev, 2) AS baseline,
  ROUND(SAFE_DIVIDE(t.revenue - b.median_rev, b.median_rev), 4) AS pct_change,
  ROUND(SAFE_DIVIDE(t.revenue - b.median_rev, GREATEST(s.robust_sd, 0.02 * b.median_rev)), 2) AS robust_z,
  ROUND(t.revenue - b.median_rev, 2) AS impact_eur
FROM daily t
JOIN baseline b USING (publisher)
JOIN spread s USING (publisher)
WHERE t.date = report_date
  AND b.weeks >= 3
  AND ABS(SAFE_DIVIDE(t.revenue - b.median_rev, b.median_rev)) >= 0.20
  AND ABS(SAFE_DIVIDE(t.revenue - b.median_rev, GREATEST(s.robust_sd, 0.02 * b.median_rev))) >= 3
ORDER BY ABS(impact_eur) DESC;
