-- Business analysis queries against the `retail_clean` view (see README for
-- the cleaning rules it applies: cancellations, bad quantities/prices, and
-- exact duplicates are already filtered out before any of these run).

-- Monthly revenue trend
SELECT
    strftime('%Y-%m', invoice_date) AS month,
    ROUND(SUM(line_total), 2) AS revenue
FROM retail_clean
GROUP BY month
ORDER BY month;

-- Total distinct customers
SELECT COUNT(DISTINCT customer_id) AS distinct_customers
FROM retail_clean;

-- Top 100 customers (by spending)
SELECT customer_id,
    SUM(line_total) AS total_spent
FROM retail_clean
WHERE customer_id IS NOT NULL
GROUP BY customer_id
ORDER BY total_spent DESC
LIMIT 100;

-- Top 100 customers (by order quantity)
SELECT customer_id, COUNT(DISTINCT invoice_no) AS total_orders
FROM retail_clean
WHERE customer_id IS NOT NULL
GROUP BY customer_id
ORDER BY total_orders DESC
LIMIT 100;

-- Best selling products by quantity
SELECT stock_code,
    SUM(quantity) AS total_sold,
    COUNT(DISTINCT invoice_no) AS num_orders,
    DENSE_RANK() OVER (ORDER BY SUM(quantity) DESC) AS quantity_rank
FROM retail_clean
WHERE customer_id IS NOT NULL
GROUP BY stock_code
ORDER BY quantity_rank ASC;

/* RFM Analysis:
   Recency   - days since last order (measured relative to the day after the last invoice date
               in the dataset, since this is historical data with no real "today")
   Frequency - number of distinct orders placed
   Monetary  - total amount spent by the customer
*/
WITH last_date AS (
    SELECT MAX(invoice_date) AS max_date FROM retail_clean
)
SELECT r.customer_id,
    CAST(julianday((SELECT max_date FROM last_date), '+1 day') -
    julianday(MAX(r.invoice_date)) AS INTEGER) AS recency_days,
    COUNT(DISTINCT r.invoice_no) AS frequency,
    ROUND(SUM(r.line_total), 2) AS monetary
FROM retail_clean r
WHERE r.customer_id IS NOT NULL
GROUP BY r.customer_id
ORDER BY monetary DESC;

/* Repeat Purchase Rate:
   % of customers with more than one distinct order
*/
WITH orders_per_customer AS (
    SELECT customer_id, COUNT(DISTINCT invoice_no) AS num_orders
    FROM retail_clean
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT
    COUNT(*) AS total_customers,
    SUM(CASE WHEN num_orders > 1 THEN 1 ELSE 0 END) AS repeat_customers,
    ROUND(100.0 * SUM(CASE WHEN num_orders > 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS repeat_rate_pct
FROM orders_per_customer;

-- Countries ranked by most customers
-- (window functions run after GROUP BY, so the aggregate can be reused
-- directly inside OVER() without a separate CTE)
SELECT
    country,
    COUNT(DISTINCT customer_id) AS total_customers,
    DENSE_RANK() OVER (ORDER BY COUNT(DISTINCT customer_id) DESC) AS country_rank
FROM retail_clean
GROUP BY country
ORDER BY country_rank;

-- Products frequently bought together (market basket)
-- Self-join on invoice_no; `stock_code_a < stock_code_b` keeps each unordered
-- pair exactly once instead of counting both (A,B) and (B,A).
SELECT
    r.stock_code AS product_a,
    r.description AS product_a_desc,
    a.stock_code AS product_b,
    a.description AS product_b_desc,
    COUNT(DISTINCT r.invoice_no) AS times_bought_together
FROM retail_clean r
JOIN retail_clean a
    ON r.invoice_no = a.invoice_no
    AND r.stock_code < a.stock_code
GROUP BY r.stock_code, r.description, a.stock_code, a.description
ORDER BY times_bought_together DESC
LIMIT 20;

-- New vs. returning customer revenue split, per month
SELECT
    month,
    CASE WHEN month = first_month THEN 'New' ELSE 'Existing' END AS customer_type,
    SUM(line_total) AS total_spent
FROM (
    SELECT
        customer_id,
        strftime('%Y-%m', invoice_date) AS month,
        MIN(strftime('%Y-%m', invoice_date)) OVER (PARTITION BY customer_id) AS first_month,
        line_total
    FROM retail_clean
    WHERE customer_id IS NOT NULL
) month_count
GROUP BY month, CASE WHEN month = first_month THEN 'New' ELSE 'Existing' END
ORDER BY month, customer_type;

/* Cohort retention: group customers by the month of their first purchase (their
   "cohort"), then track what % of that cohort is still buying N months later.
   cohort_index/txn_index encode each month as (year*12 + month) so subtracting
   them gives a clean month count that's correct across year boundaries.
*/
WITH customer_cohort AS (
    SELECT
        customer_id,
        MIN(strftime('%Y-%m', invoice_date)) AS cohort_month,
        MIN(CAST(strftime('%Y', invoice_date) AS INTEGER) * 12
            + CAST(strftime('%m', invoice_date) AS INTEGER)) AS cohort_index
    FROM retail_clean
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
),
customer_activity AS (
    SELECT
        r.customer_id,
        cc.cohort_month,
        (CAST(strftime('%Y', r.invoice_date) AS INTEGER) * 12
         + CAST(strftime('%m', r.invoice_date) AS INTEGER)) - cc.cohort_index AS month_number
    FROM retail_clean r
    JOIN customer_cohort cc ON r.customer_id = cc.customer_id
),
cohort_table AS (
    SELECT cohort_month, month_number, COUNT(DISTINCT customer_id) AS active_customers
    FROM customer_activity
    GROUP BY cohort_month, month_number
),
cohort_size AS (
    SELECT cohort_month, active_customers AS cohort_total
    FROM cohort_table
    WHERE month_number = 0
)
SELECT
    ct.cohort_month,
    ct.month_number,
    ct.active_customers,
    cs.cohort_total,
    ROUND(100.0 * ct.active_customers / cs.cohort_total, 1) AS retention_pct
FROM cohort_table ct
JOIN cohort_size cs ON ct.cohort_month = cs.cohort_month
ORDER BY ct.cohort_month, ct.month_number;
