# Step-by-Step: SQL + Python Customer Analytics Project

This walks through the whole pipeline: raw file -> SQL -> Python -> dashboard -> GitHub,
using the tools already set up in this project. Each step says what to do, why, and
how to check you did it right.

---

## 0. Your toolkit (already installed)

| Tool | Purpose | Status |
|---|---|---|
| Python 3.13 | scripting, analysis | installed |
| pandas, openpyxl, matplotlib | data handling + charts | installed |
| SQLite (via Python's `sqlite3`, built in) | the database engine | in use |
| VS Code | editor | installed |
| SQLTools + SQLite driver (VS Code extensions) | run SQL against the .db file | installed, connection pre-configured |
| SQLite Viewer (VS Code extension) | browse the .db file visually | installed |
| git | version control / GitHub | installed |

Nothing else is required for this dataset size (~540k rows). If you later work with
a much bigger dataset or want real SQL Server / Postgres experience for job applications,
that's a separate, bigger step — ask me when you get there.

---

## 1. Load the dataset into SQL

**What we did:** `scripts/load_data.py` reads the raw `.xlsx`, does light renaming, and
writes it into `data/customer_analytics.db` as a table called `retail` using
`pandas.DataFrame.to_sql()`.

**Why load through Python instead of a GUI import wizard:** it's repeatable (delete the
`.db` and rerun the script any time) and lets you fix column names/types in code instead
of clicking through a wizard each time.

**Try it yourself:**
```bash
python scripts/load_data.py
```
Then confirm it worked, either:
- In VS Code: click `data/customer_analytics.db` (SQLite Viewer opens it), or
- In SQLTools sidebar: connect to `customer_analytics`, expand it, see the `retail` table.

**Alternative (GUI) approach**, if you ever want to import a plain CSV without writing
Python: [DB Browser for SQLite](https://sqlitebrowser.org/) has a "File > Import > Table
from CSV" wizard. Good to know exists, not needed here.

---

## 2. Clean the data in SQL

SQL is good at *set-based* cleaning: filtering out bad rows, deduplicating, and
standardizing values — before the data ever reaches Python. Real issues found in this
dataset (checked directly against your `retail` table):

| Issue | Count | Query to find it |
|---|---|---|
| Negative quantity, not a flagged cancellation | 1,336 rows | `SELECT COUNT(*) FROM retail WHERE quantity < 0 AND is_cancellation = 0;` |
| Zero or negative unit price (likely bad-debt/adjustment entries, not real sales) | 2,517 rows | `SELECT COUNT(*) FROM retail WHERE unit_price <= 0;` |
| Exact duplicate line items | 4,993 rows | see query below |
| Messy country values (`Unspecified`, `European Community`) | a few hundred rows | `SELECT DISTINCT country FROM retail;` |

**The pattern to learn:** don't overwrite your raw table. Create a SQL **VIEW** that
represents the "clean" version — a saved query that always reflects current cleaning
logic, without duplicating data or destroying the original:

```sql
CREATE VIEW retail_clean AS
SELECT DISTINCT  -- drops the ~4,993 exact duplicates
    invoice_no, stock_code, description, quantity, invoice_date,
    unit_price, customer_id, country, is_cancellation, line_total
FROM retail
WHERE
    quantity > 0                 -- drop bad negative-quantity rows not tied to a cancellation
    AND unit_price > 0           -- drop zero/negative price adjustment rows
    AND country NOT IN ('Unspecified');
```

Run that once (via SQLTools, or `sqlite3 data/customer_analytics.db` on the command
line), then from then on, **query `retail_clean` instead of `retail`** for any real
analysis. Try adapting the queries in `sql/analysis_queries.sql` to use `retail_clean`
and see how the numbers shift.

**Why this matters for interviews:** "I found and handled negative quantities, duplicate
rows, and inconsistent categorical values with SQL before analysis" is a concrete,
specific thing to say about this project — much stronger than "I cleaned the data."

---

## 3. Import the (clean) data into Python

Connect with the built-in `sqlite3` module, and use `pandas.read_sql()` to pull query
results straight into a DataFrame — this is the same pattern used in
`scripts/rfm_analysis.py`:

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("data/customer_analytics.db")
df = pd.read_sql("SELECT * FROM retail_clean;", conn)
conn.close()

df.info()          # types, non-null counts
df.describe()      # numeric summary
df.head()
```

**Why do cleaning partly in SQL and partly in Python, instead of all in one place?**
Rule of thumb: use SQL for filtering/deduplication/aggregation (it's fast and set-based),
use Python for anything row-by-row, statistical, or that needs a plotting/ML library.
There's no single "correct" split — this is a judgment call you'll develop with practice.

---

## 4. Clean/prepare the data further in Python

Once it's a DataFrame, check for things SQL doesn't easily catch:

```python
df.isna().sum()                      # missing values per column
df.dtypes                            # are types what you expect? (dates as datetime?)
df["invoice_date"] = pd.to_datetime(df["invoice_date"])
df["customer_id"] = df["customer_id"].astype("Int64")  # nullable int

# outlier check - e.g. extreme quantities that might be wholesale, not retail, orders
df["quantity"].describe()
df[df["quantity"] > df["quantity"].quantile(0.999)]  # look at the top 0.1%
```

Best practice: never edit `df` cell-by-cell by hand. Write cleaning steps as code (like
above) so they're reproducible and you can explain exactly what you did and why — that's
what `scripts/rfm_analysis.py` already does for the RFM scoring logic.

---

## 5. Build a dashboard

Recommended: **Streamlit** — pure Python, no separate BI tool to learn, quick to get
something real on screen, and it's a common tool to see on data analyst portfolios.

```bash
pip install streamlit
```

Create `scripts/dashboard.py`:
```python
import sqlite3
import pandas as pd
import streamlit as st

conn = sqlite3.connect("data/customer_analytics.db")
monthly = pd.read_sql("SELECT strftime('%Y-%m', invoice_date) month, SUM(line_total) revenue "
                       "FROM retail_clean GROUP BY month ORDER BY month;", conn)
top_customers = pd.read_sql("SELECT customer_id, SUM(line_total) spend FROM retail_clean "
                             "WHERE customer_id IS NOT NULL GROUP BY customer_id "
                             "ORDER BY spend DESC LIMIT 10;", conn)
conn.close()

st.title("Customer Analytics Dashboard")
st.metric("Total revenue", f"£{monthly['revenue'].sum():,.0f}")

st.subheader("Monthly revenue")
st.line_chart(monthly.set_index("month")["revenue"])

st.subheader("Top 10 customers")
st.bar_chart(top_customers.set_index("customer_id")["spend"])
```

Run it:
```bash
streamlit run scripts/dashboard.py
```
It opens in your browser at `http://localhost:8501`. Add more charts/filters as you get
comfortable (a country dropdown with `st.selectbox`, a date range with `st.slider`, the
RFM segment breakdown from `outputs/rfm_segments.csv`, etc.).

*Alternative:* if a job posting specifically asks for Power BI or Tableau experience,
those are worth learning too — but they're separate tools with their own learning curve,
not a natural "next line of code" from here. Ask me if you want to go that route instead.

---

## 6. Upload the project to GitHub

1. **Decide what NOT to commit.** The raw `.xlsx` (23 MB) and `.db` file are large
   binary files — fine for personal use, but bloat a git repo and add little value to
   someone reviewing your code. A `.gitignore` is already added to this project excluding
   them (see `.gitignore`); the README explains how to regenerate them by running
   `load_data.py`.

2. **Initialize the repo** (from the project folder):
   ```bash
   git init
   git add .
   git commit -m "Initial customer analytics project"
   ```

3. **Create the GitHub repo and push.** Easiest via the GitHub website:
   - Go to github.com -> New repository -> name it (e.g. `customer-analytics-portfolio`)
     -> do **not** initialize with a README (you already have one) -> Create.
   - Copy the commands GitHub shows you, which look like:
     ```bash
     git remote add origin https://github.com/<your-username>/customer-analytics-portfolio.git
     git branch -M main
     git push -u origin main
     ```

4. **Polish for reviewers:** make sure `README.md` at the project root explains what the
   project does, how to run it, and what you learned — it already does. Consider adding
   a screenshot of the dashboard or the RFM chart to the README once you've built one.

I can walk through any of these steps live when you get to them, or help debug if a
command errors — just paste what you see.
