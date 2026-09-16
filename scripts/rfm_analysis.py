"""
Customer segmentation via RFM (Recency, Frequency, Monetary) analysis.

Pulls the RFM base table straight from SQL (see sql/analysis_queries.sql, the
RFM Analysis query), scores each customer 1-5 on each dimension via quintiles, and buckets them into
named segments (Champions, At Risk, Lost, etc.) -- a standard business analytics
technique for deciding who to target with retention/marketing efforts.

Run: python scripts/rfm_analysis.py
Outputs: outputs/rfm_segments.csv, outputs/rfm_segment_counts.png, outputs/monthly_revenue.png
"""
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

def _find_project_root() -> Path:
    path = Path(__file__).resolve()
    while not (path / ".git").exists():
        if path == path.parent:
            raise RuntimeError("Could not find project root (no .git folder found)")
        path = path.parent
    return path


ROOT = _find_project_root()
DB_PATH = ROOT / "data" / "customer_analytics.db"
OUT_DIR = ROOT / "outputs"

RFM_QUERY = """
WITH last_date AS (
    SELECT MAX(invoice_date) AS max_date FROM retail
)
SELECT
    r.customer_id,
    CAST(julianday((SELECT max_date FROM last_date), '+1 day') - julianday(MAX(r.invoice_date)) AS INTEGER) AS recency_days,
    COUNT(DISTINCT r.invoice_no) AS frequency,
    ROUND(SUM(r.line_total), 2) AS monetary
FROM retail r
WHERE r.is_cancellation = 0 AND r.customer_id IS NOT NULL
GROUP BY r.customer_id;
"""

MONTHLY_REVENUE_QUERY = """
SELECT
    strftime('%Y-%m', invoice_date) AS month,
    ROUND(SUM(line_total), 2) AS revenue
FROM retail
WHERE is_cancellation = 0
GROUP BY month
ORDER BY month;
"""


def score_quintile(series: pd.Series, reverse: bool = False) -> pd.Series:
    """1-5 score by quintile. reverse=True means lower raw value -> higher score
    (used for recency, where fewer days-since-last-order is better)."""
    ranks = pd.qcut(series.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    scores = ranks.astype(int)
    return (6 - scores) if reverse else scores


def segment_customer(row) -> str:
    r, f, m = row["r_score"], row["f_score"], row["m_score"]
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r >= 3 and f >= 3:
        return "Loyal Customers"
    if r >= 4 and f <= 2:
        return "New / Recent Customers"
    if r <= 2 and f >= 4:
        return "At Risk"
    if r <= 2 and f <= 2 and m <= 2:
        return "Lost"
    return "Needs Attention"


def main():
    OUT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    rfm = pd.read_sql(RFM_QUERY, conn)
    rfm["r_score"] = score_quintile(rfm["recency_days"], reverse=True)
    rfm["f_score"] = score_quintile(rfm["frequency"])
    rfm["m_score"] = score_quintile(rfm["monetary"])
    rfm["segment"] = rfm.apply(segment_customer, axis=1)

    rfm.sort_values("monetary", ascending=False).to_csv(OUT_DIR / "rfm_segments.csv", index=False)
    print("Segment counts:")
    print(rfm["segment"].value_counts())

    # Chart 1: segment counts
    counts = rfm["segment"].value_counts().sort_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    counts.plot(kind="barh", ax=ax, color="#4C72B0")
    ax.set_xlabel("Number of customers")
    ax.set_title("Customer segments (RFM)")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "rfm_segment_counts.png", dpi=150)
    plt.close(fig)

    # Chart 2: monthly revenue trend
    monthly = pd.read_sql(MONTHLY_REVENUE_QUERY, conn)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(monthly["month"], monthly["revenue"], marker="o", color="#4C72B0")
    ax.set_xlabel("Month")
    ax.set_ylabel("Revenue")
    ax.set_title("Monthly revenue")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "monthly_revenue.png", dpi=150)
    plt.close(fig)

    conn.close()
    print(f"\nSaved outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
