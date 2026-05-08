"""
tests/test_bq_cost_query.py
────────────────────────────
Pytest tests for the BigQuery cost query builder.

Domain constraints under test:
  • Partition filter on order_date must be present
  • Estimated scanned bytes must be below 10 GB
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

BYTES_PER_GB      = 1_073_741_824
MAX_SCANNED_BYTES = 10 * BYTES_PER_GB


# ── Test the BUGGY version (documents the failures) ──────────────────────────

class TestBuggyQuery:

    def test_query_missing_partition_filter(self):
        """Buggy query has no partition filter — cost constraint violated."""
        from bugs.bq_cost_query import build_order_query, check_cost_constraint

        query  = build_order_query("COMPLETED", "2024-01-01", "2024-01-31")
        result = check_cost_constraint(query)

        # The bug: order_date appears in SELECT but NOT in WHERE as a filter
        # Check that there's no WHERE filter on order_date (no BETWEEN / >= etc.)
        import re
        has_where_filter = bool(re.search(
            r"where.*order_date.*(between|>=|<=|>|<)", query.lower(), re.DOTALL
        ))
        assert not has_where_filter, (
            "Buggy version should NOT filter on order_date in WHERE clause"
        )
        assert result["passed"] is False, "Cost constraint should fail on buggy query"
        assert result["scanned_gb"] > 10

    def test_estimated_cost_is_high(self):
        """Full table scan on 180 TB table is very expensive."""
        from bugs.bq_cost_query import build_order_query, estimate_scanned_bytes, estimate_cost_usd
        query   = build_order_query("COMPLETED")
        scanned = estimate_scanned_bytes(query)
        cost    = estimate_cost_usd(scanned)
        assert cost > 100, f"Expected cost > $100, got ${cost}"


# ── Test the FIXED version ────────────────────────────────────────────────────

class TestFixedQuery:

    def test_partition_filter_present(self):
        """Fixed query must include order_date partition filter."""
        from bugs.bq_cost_query_fixed import build_order_query

        query = build_order_query("COMPLETED", "2024-01-01", "2024-01-31")
        assert "order_date" in query.lower(), (
            "Fixed query must include order_date partition filter"
        )
        assert "between" in query.lower() or ">=" in query.lower()

    def test_cost_constraint_passes(self):
        """Fixed query must satisfy the 10 GB scanned bytes constraint."""
        from bugs.bq_cost_query_fixed import build_order_query, check_cost_constraint

        query  = build_order_query("COMPLETED", "2024-01-01", "2024-01-31")
        result = check_cost_constraint(query)

        assert result["passed"] is True, (
            f"Cost constraint should pass. Scanned: {result['scanned_gb']} GB. "
            f"Violation: {result['violation']}"
        )
        assert result["scanned_bytes"] <= MAX_SCANNED_BYTES

    def test_default_date_range_also_filtered(self):
        """Even without explicit dates, fixed version applies a default filter."""
        from bugs.bq_cost_query_fixed import build_order_query, check_cost_constraint

        query  = build_order_query("PENDING")   # no dates supplied
        result = check_cost_constraint(query)
        assert result["passed"] is True, (
            "Fixed version must default to a safe date range"
        )

    def test_cost_is_low(self):
        """Fixed query cost must be under $1 for a 10-day window."""
        from bugs.bq_cost_query_fixed import build_order_query, estimate_scanned_bytes, estimate_cost_usd

        query   = build_order_query("COMPLETED", "2024-01-01", "2024-01-10")
        scanned = estimate_scanned_bytes(query)
        cost    = estimate_cost_usd(scanned)
        assert cost < 1.0, f"Expected cost < $1, got ${cost}"

    def test_status_filter_preserved(self):
        """Partition filter must not remove the status filter."""
        from bugs.bq_cost_query_fixed import build_order_query

        query = build_order_query("REFUNDED", "2024-01-01", "2024-01-31")
        assert "REFUNDED" in query
        assert "order_date" in query.lower()
