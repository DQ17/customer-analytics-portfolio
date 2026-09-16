"""
Loads the UCI Online Retail dataset (xlsx) into a SQLite database,
doing light cleaning along the way (real transactional data is messy).

Run: python scripts/load_data.py
"""
import sqlite3
from pathlib import Path

import pandas as pd

def _find_project_root() -> Path:
    path = Path(__file__).resolve()
    while not (path / ".git").exists():
        if path == path.parent:
            raise RuntimeError("Could not find project root (no .git folder found)")
        path = path.parent
    return path


ROOT = _find_project_root()
SRC_XLSX = ROOT / "data" / "online_retail.xlsx"
DB_PATH = ROOT / "data" / "customer_analytics.db"


def main():
    print(f"Reading {SRC_XLSX} ...")
    df = pd.read_excel(SRC_XLSX)

    print(f"Raw rows: {len(df):,}")
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    # invoicedate -> invoice_date etc.
    df = df.rename(columns={"invoiceno": "invoice_no", "stockcode": "stock_code",
                             "invoicedate": "invoice_date", "unitprice": "unit_price",
                             "customerid": "customer_id"})

    # A "C" prefix on invoice_no marks a cancellation - keep it, but flag it,
    # since cancellations are their own business signal (returns/refunds).
    df["is_cancellation"] = df["invoice_no"].astype(str).str.startswith("C")

    df["customer_id"] = df["customer_id"].astype("Int64")  # nullable int, many rows have no customer_id
    df["line_total"] = df["quantity"] * df["unit_price"]

    print(f"Rows with no customer_id (guest/unlinked): {df['customer_id'].isna().sum():,}")
    print(f"Cancellation rows: {df['is_cancellation'].sum():,}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql("retail", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_id ON retail(customer_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_invoice_date ON retail(invoice_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON retail(country);")

    print(f"Loaded into {DB_PATH} as table 'retail' ({len(df):,} rows).")


if __name__ == "__main__":
    main()
