"""
Full pandas analysis of the customer_analytics dataset - mirrors every query
in sql/analysis_queries.sql, section by section, so you can compare the SQL
and pandas versions of the same question side by side.

Run: python scripts/python_analysis.py
Outputs: prints every result table to the terminal, saves charts + CSVs to outputs/
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
OUT_DIR.mkdir(exist_ok=True)

pd.set_option("display.width", 120)
pd.set_option("display.max_columns", 12)


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    # --- Load data (same source as SQL - the already-cleaned view) ---
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM retail_clean;", conn)
    conn.close()

    df["invoice_date"] = pd.to_datetime(df["invoice_date"])
    df["month"] = df["invoice_date"].dt.to_period("M").astype(str)

    # `known` = rows with a real customer_id (guest/unlinked transactions excluded),
    # same filter used throughout the SQL side. .copy() avoids a SettingWithCopyWarning
    # since this DataFrame gets new columns added to it below.
    known = df[df["customer_id"].notna()].copy()
    known["customer_id"] = known["customer_id"].astype(int)

    section("0. DATASET OVERVIEW")
    print(f"Rows: {len(df):,}   Columns: {df.shape[1]}")
    print("\nColumn types:")
    print(df.dtypes)
    print("\nMissing values per column:")
    print(df.isna().sum())

    # --- 1. Monthly revenue trend ---
    section("1. MONTHLY REVENUE TREND")
    monthly_revenue = df.groupby("month")["line_total"].sum().round(2)
    print(monthly_revenue)
    monthly_revenue.to_csv(OUT_DIR / "python_monthly_revenue.csv")

    # --- 2. Total distinct customers ---
    section("2. TOTAL DISTINCT CUSTOMERS")
    distinct_customers = df["customer_id"].nunique()
    print(f"Distinct customers: {distinct_customers:,}")

    # --- 3. Top 100 customers by spending ---
    section("3. TOP CUSTOMERS BY SPENDING (top 10 of 100 shown)")
    top_spenders = (
        known.groupby("customer_id")["line_total"]
        .sum()
        .round(2)
        .sort_values(ascending=False)
        .head(100)
        .rename("total_spent")
    )
    print(top_spenders.head(10))
    top_spenders.to_csv(OUT_DIR / "python_top_customers_by_spend.csv")

    # --- 4. Top 100 customers by order count ---
    section("4. TOP CUSTOMERS BY ORDER COUNT (top 10 of 100 shown)")
    top_orders = (
        known.groupby("customer_id")["invoice_no"]
        .nunique()
        .sort_values(ascending=False)
        .head(100)
        .rename("total_orders")
    )
    print(top_orders.head(10))

    # --- 5. Best selling products by quantity ---
    section("5. BEST SELLING PRODUCTS BY QUANTITY (top 10 shown)")
    products = (
        known.groupby("stock_code")
        .agg(total_sold=("quantity", "sum"), num_orders=("invoice_no", "nunique"))
        .sort_values("total_sold", ascending=False)
    )
    products["quantity_rank"] = products["total_sold"].rank(method="dense", ascending=False).astype(int)
    print(products.head(10))

    # --- 6. RFM Analysis + segmentation ---
    section("6. RFM ANALYSIS (top 10 by monetary shown)")
    ref_date = df["invoice_date"].max() + pd.Timedelta(days=1)
    rfm = (
        known.groupby("customer_id")
        .agg(
            recency_days=("invoice_date", lambda x: (ref_date - x.max()).days),
            frequency=("invoice_no", "nunique"),
            monetary=("line_total", "sum"),
        )
        .round(2)
        .sort_values("monetary", ascending=False)
    )
    print(rfm.head(10))

    # Quintile scoring: lower recency_days is better (labels reversed), higher
    # frequency/monetary is better (labels in normal order).
    rfm["r_score"] = pd.qcut(rfm["recency_days"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    rfm["f_score"] = pd.qcut(rfm["frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["m_score"] = pd.qcut(rfm["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)

    def segment(row):
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

    rfm["segment"] = rfm.apply(segment, axis=1)
    print("\nSegment counts:")
    print(rfm["segment"].value_counts())
    rfm.to_csv(OUT_DIR / "python_rfm.csv")

    # --- 7. Repeat purchase rate ---
    section("7. REPEAT PURCHASE RATE")
    orders_per_customer = known.groupby("customer_id")["invoice_no"].nunique()
    total_customers = len(orders_per_customer)
    repeat_customers = int((orders_per_customer > 1).sum())
    repeat_rate_pct = round(100 * repeat_customers / total_customers, 1)
    print(f"Total customers:   {total_customers:,}")
    print(f"Repeat customers:  {repeat_customers:,}")
    print(f"Repeat rate:       {repeat_rate_pct}%")

    # --- 8. Countries ranked by most customers ---
    section("8. COUNTRIES RANKED BY MOST CUSTOMERS (top 10 shown)")
    countries = (
        df.groupby("country")["customer_id"]
        .nunique()
        .sort_values(ascending=False)
        .rename("total_customers")
        .reset_index()
    )
    countries["country_rank"] = countries["total_customers"].rank(method="dense", ascending=False).astype(int)
    print(countries.head(10))

    # --- 9. Products frequently bought together ---
    section("9. PRODUCTS FREQUENTLY BOUGHT TOGETHER (top 10 shown)")
    print("(self-merge on invoice_no - this takes a moment)")
    pairs_source = df[["invoice_no", "stock_code", "description"]].drop_duplicates()
    merged = pairs_source.merge(pairs_source, on="invoice_no", suffixes=("_a", "_b"))
    # stock_code_a < stock_code_b keeps each unordered pair exactly once
    # instead of counting both (A,B) and (B,A) as separate pairs.
    merged = merged[merged["stock_code_a"] < merged["stock_code_b"]]
    basket = (
        merged.groupby(["stock_code_a", "description_a", "stock_code_b", "description_b"])["invoice_no"]
        .nunique()
        .sort_values(ascending=False)
        .rename("times_bought_together")
        .reset_index()
    )
    print(basket.head(10))
    basket.head(100).to_csv(OUT_DIR / "python_market_basket.csv", index=False)

    # --- 10. New vs returning customer revenue split, per month ---
    section("10. NEW VS RETURNING CUSTOMER REVENUE SPLIT (first 6 rows shown)")
    known["first_purchase_date"] = known.groupby("customer_id")["invoice_date"].transform("min")
    known["first_month"] = known["first_purchase_date"].dt.to_period("M").astype(str)
    known["customer_type"] = "Existing"
    known.loc[known["month"] == known["first_month"], "customer_type"] = "New"
    new_vs_existing = known.groupby(["month", "customer_type"])["line_total"].sum().round(2)
    print(new_vs_existing.head(6))
    new_vs_existing.to_csv(OUT_DIR / "python_new_vs_existing.csv")

    # --- 11. Cohort retention ---
    # Group customers by the month of their first purchase (their "cohort"), then
    # track what % of that cohort is still buying N months later. Encoding each
    # month as (year*12 + month) turns "months apart" into simple subtraction
    # that's correct across year boundaries (e.g. Dec 2010 -> Jan 2011 = 1).
    section("11. COHORT RETENTION (first 2 cohorts shown)")
    known["cohort_month"] = known["first_month"]
    known["cohort_index"] = (
        known["first_purchase_date"].dt.year * 12 + known["first_purchase_date"].dt.month
    )
    known["txn_index"] = known["invoice_date"].dt.year * 12 + known["invoice_date"].dt.month
    known["month_number"] = known["txn_index"] - known["cohort_index"]

    cohort_table = (
        known.groupby(["cohort_month", "month_number"])["customer_id"]
        .nunique()
        .rename("active_customers")
        .reset_index()
    )
    cohort_size = cohort_table[cohort_table["month_number"] == 0][["cohort_month", "active_customers"]]
    cohort_size = cohort_size.rename(columns={"active_customers": "cohort_total"})
    cohort_table = cohort_table.merge(cohort_size, on="cohort_month")
    cohort_table["retention_pct"] = round(100 * cohort_table["active_customers"] / cohort_table["cohort_total"], 1)
    print(cohort_table[cohort_table["cohort_month"].isin(["2010-12", "2011-01"])])
    cohort_table.to_csv(OUT_DIR / "python_cohort_retention.csv", index=False)

    # --- Charts ---
    section("CHARTS - saving to outputs/")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(monthly_revenue.index.astype(str), monthly_revenue.values, marker="o", color="#4C72B0")
    ax.set_title("Monthly Revenue")
    ax.set_xlabel("Month")
    ax.set_ylabel("Revenue")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "python_monthly_revenue.png", dpi=150)
    plt.close(fig)

    seg_counts = rfm["segment"].value_counts().sort_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    seg_counts.plot(kind="barh", ax=ax, color="#55A868")
    ax.set_title("Customer Segments (RFM)")
    ax.set_xlabel("Number of customers")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "python_rfm_segments.png", dpi=150)
    plt.close(fig)

    cohort_pivot = cohort_table.pivot(index="cohort_month", columns="month_number", values="retention_pct")
    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(cohort_pivot.values, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(cohort_pivot.columns)))
    ax.set_xticklabels(cohort_pivot.columns)
    ax.set_yticks(range(len(cohort_pivot.index)))
    ax.set_yticklabels(cohort_pivot.index)
    ax.set_xlabel("Months since first purchase")
    ax.set_ylabel("Cohort")
    ax.set_title("Cohort Retention Heatmap (%)")
    fig.colorbar(im, ax=ax, label="Retention %")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "python_cohort_heatmap.png", dpi=150)
    plt.close(fig)

    print("Saved: python_monthly_revenue.png, python_rfm_segments.png, python_cohort_heatmap.png")
    print(f"\nAll done. Full result tables saved as CSVs in {OUT_DIR}")


if __name__ == "__main__":
    main()
