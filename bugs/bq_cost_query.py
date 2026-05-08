"""
bugs/bq_cost_query.py
──────────────────────
BigQuery query builder for the orders analytics table.

BUG: build_order_query() does not add a partition filter on
`order_date`. BigQuery partitioned tables perform a full table scan
when no partition filter is present, scanning ALL historical data.

At current table size (~500 GB/day * 365 days = ~180 TB) a single
unfiltered query costs ~$900 at $5/TB.

Domain constraints:
  • "Require partition filter on order_date"
  • "Estimated scanned bytes must be below 10 GB per query"

The fix: add WHERE order_date BETWEEN @start_date AND @end_date
using query parameters so BigQuery can prune partitions.
"""

from __future__ import annotations

BYTES_PER_GB   = 1_073_741_824
COST_PER_TB    = 5.00           # USD, BigQuery on-demand pricing
TABLE_SIZE_TB  = 180.0          # approximate full table size

# Domain constraint threshold
MAX_SCANNED_BYTES = 10 * BYTES_PER_GB   # 10 GB


def build_order_query(
    status: str,
    start_date: str | None = None,
    end_date:   str | None = None,
) -> str:
    """
    Build a SQL query to fetch orders by status.

    BUG: partition filter is never applied even when start_date /
    end_date are provided. The WHERE clause only filters on status,
    causing a full table scan every time.
    """
    # BUG: ignores start_date and end_date entirely
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
    status = '{status}'
"""
    return query.strip()


def estimate_scanned_bytes(query: str) -> int:
    """
    Estimate bytes scanned by inspecting the query for partition filters.
    Returns full table size if no partition filter is found.
    """
    query_lower = query.lower()
    has_partition_filter = (
        "order_date" in query_lower
        and ("between" in query_lower or ">=" in query_lower or "<=" in query_lower)
    )
    if has_partition_filter:
        # Rough estimate: ~10 days of data for a typical date range
        return int(TABLE_SIZE_TB * BYTES_PER_GB * 1024 * 10 / 365)
    else:
        # Full table scan
        return int(TABLE_SIZE_TB * BYTES_PER_GB * 1024)


def estimate_cost_usd(scanned_bytes: int) -> float:
    scanned_tb = scanned_bytes / (BYTES_PER_GB * 1024)
    return round(scanned_tb * COST_PER_TB, 2)


def check_cost_constraint(query: str) -> dict:
    """
    Check whether the query satisfies the domain cost constraint.
    Returns a structured result for the verifier.
    """
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
            f"Query scans {round(scanned/BYTES_PER_GB,1)} GB "
            f"(${cost}) — exceeds {round(MAX_SCANNED_BYTES/BYTES_PER_GB,0):.0f} GB threshold"
        ),
    }
