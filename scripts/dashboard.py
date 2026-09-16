"""
Interactive dashboard for the customer analytics project.

Run: streamlit run scripts/dashboard.py
"""
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


def _find_project_root() -> Path:
    path = Path(__file__).resolve()
    while not (path / ".git").exists():
        if path == path.parent:
            raise RuntimeError("Could not find project root (no .git folder found)")
        path = path.parent
    return path


ROOT = _find_project_root()
DB_PATH = ROOT / "data" / "customer_analytics.db"

st.set_page_config(page_title="Customer Analytics Dashboard", layout="wide")


@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM retail_clean WHERE customer_id IS NOT NULL;", conn)
    conn.close()
    df["invoice_date"] = pd.to_datetime(df["invoice_date"])
    df["month"] = df["invoice_date"].dt.to_period("M").astype(str)
    return df


df = load_data()
ref_date = df["invoice_date"].max() + pd.Timedelta(days=1)

st.title("Customer Analytics Dashboard")

countries = ["All"] + sorted(df["country"].unique().tolist())
selected_country = st.sidebar.selectbox("Country", countries)
filtered = df if selected_country == "All" else df[df["country"] == selected_country]

# --- KPI row ---
orders_per_customer = filtered.groupby("customer_id")["invoice_no"].nunique()
repeat_rate = 100 * (orders_per_customer > 1).sum() / len(orders_per_customer) if len(orders_per_customer) else 0

col1, col2, col3 = st.columns(3)
col1.metric("Total Revenue", f"£{filtered['line_total'].sum():,.0f}")
col2.metric("Distinct Customers", f"{filtered['customer_id'].nunique():,}")
col3.metric("Repeat Purchase Rate", f"{repeat_rate:.1f}%")

# --- Monthly revenue ---
st.subheader("Monthly Revenue")
monthly = filtered.groupby("month")["line_total"].sum()
st.line_chart(monthly)

# --- Top customers / top products ---
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Top 10 Customers by Spend")
    top_customers = filtered.groupby("customer_id")["line_total"].sum().sort_values(ascending=False).head(10)
    st.bar_chart(top_customers)
with col_b:
    st.subheader("Top 10 Best-Selling Products")
    top_products = filtered.groupby("stock_code")["quantity"].sum().sort_values(ascending=False).head(10)
    st.bar_chart(top_products)

# --- RFM segments ---
st.subheader("Customer Segments (RFM)")
rfm = filtered.groupby("customer_id").agg(
    recency_days=("invoice_date", lambda x: (ref_date - x.max()).days),
    frequency=("invoice_no", "nunique"),
    monetary=("line_total", "sum"),
)
if len(rfm) >= 5:
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
    st.bar_chart(rfm["segment"].value_counts())
else:
    st.info("Not enough customers in this selection to compute RFM segments.")

# --- Cohort retention heatmap ---
st.subheader("Cohort Retention (%)")
cohort_df = filtered.copy()
cohort_df["first_purchase_date"] = cohort_df.groupby("customer_id")["invoice_date"].transform("min")
cohort_df["cohort_month"] = cohort_df["first_purchase_date"].dt.to_period("M").astype(str)
cohort_df["cohort_index"] = cohort_df["first_purchase_date"].dt.year * 12 + cohort_df["first_purchase_date"].dt.month
cohort_df["txn_index"] = cohort_df["invoice_date"].dt.year * 12 + cohort_df["invoice_date"].dt.month
cohort_df["month_number"] = cohort_df["txn_index"] - cohort_df["cohort_index"]

cohort_table = (
    cohort_df.groupby(["cohort_month", "month_number"])["customer_id"]
    .nunique().rename("active_customers").reset_index()
)
cohort_size = cohort_table[cohort_table["month_number"] == 0][["cohort_month", "active_customers"]]
cohort_size = cohort_size.rename(columns={"active_customers": "cohort_total"})
cohort_table = cohort_table.merge(cohort_size, on="cohort_month")
cohort_table["retention_pct"] = round(100 * cohort_table["active_customers"] / cohort_table["cohort_total"], 1)

cohort_pivot = cohort_table.pivot(index="cohort_month", columns="month_number", values="retention_pct")
st.dataframe(cohort_pivot.style.background_gradient(cmap="YlGnBu", axis=None).format("{:.1f}", na_rep=""))
