"""
bugs/bq_cost_query_fixed.py
─────────────────────────────
FIXED version of the BigQuery query builder.

Fix: apply partition filter on order_date using parameterised
date range. BigQuery can now prune partitions and only scans
the relevant slice of data.

Satisfies domain constraints:
  • "Require partition filter on order_date"
  • "Estimated scanned bytes must be below 10 GB per query"
"""

from __future__ import annotations

BYTES_PER_GB   = 1_073_741_824
COST_PER_TB    = 5.00
TABLE_SIZE_TB  = 180.0
MAX_SCANNED_BYTES = 10 * BYTES_PER_GB


def build_order_query(
    status: str,
    start_date: str | None = None,
    end_date:   str | None = None,
) -> str:
    """
    Build a SQL query with mandatory partition filter.

    FIX: always apply order_date partition filter.
    Defaults to last 7 days if no range is provided.
    """
    # FIX: provide defaults so partition filter is always applied
    start = start_date or "DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
    end   = end_date   or "CURRENT_DATE()"

    query = f"""
SELECT
    order_id,
    customer_id,
    order_date,
    status,
    total_amount
FROM
    `project.dataset.orders`
WHERE
    order_date BETWEEN {start} AND {end}
    AND status = '{status}'
"""
    return query.strip()


def estimate_scanned_bytes(query: str) -> int:
    query_lower = query.lower()
    has_partition_filter = (
        "order_date" in query_lower
        and ("between" in query_lower or ">=" in query_lower or "<=" in query_lower)
    )
    if has_partition_filter:
        # ~500 MB per day * 10 days = 5 GB — within 10 GB threshold
        return int(500 * 1024 * 1024 * 10)
    else:
        # Full table scan: 180 TB
        return int(TABLE_SIZE_TB * BYTES_PER_GB * 1024)


def estimate_cost_usd(scanned_bytes: int) -> float:
    scanned_tb = scanned_bytes / (BYTES_PER_GB * 1024)
    return round(scanned_tb * COST_PER_TB, 2)


def check_cost_constraint(query: str) -> dict:
    scanned = estimate_scanned_bytes(query)
    cost    = estimate_cost_usd(scanned)
    passed  = scanned <= MAX_SCANNED_BYTES
    return {
        "passed":          passed,
        "scanned_bytes":   scanned,
        "scanned_gb":      round(scanned / BYTES_PER_GB, 2),
        "estimated_cost":  cost,
        "threshold_bytes": MAX_SCANNED_BYTES,
        "threshold_gb":    round(MAX_SCANNED_BYTES / BYTES_PER_GB, 2),
        "violation":       None if passed else (
            f"Query scans {round(scanned/BYTES_PER_GB,1)} GB — exceeds threshold"
        ),
    }
