"""
verifier.py
────────────
Person A's second deliverable.

Interface:
    verify_patch(repo_path, incident) -> verification_result.json

Runs three checks:
  1. pytest suite on the patched repo
  2. Domain cost constraint (BigQuery incidents)
  3. Domain duplicate-event constraint (pipeline incidents)

Returns a structured verification_result dict that Person B's
Verification Agent can consume directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import importlib.util
from pathlib import Path
from typing import Any


# ── Load constraint definitions ───────────────────────────────────────────────

def _load_constraints(constraint_ids: list[str], repo_path: str) -> list[dict]:
    constraints_dir = Path(repo_path) / "constraints"
    all_constraints = []
    for cfile in constraints_dir.glob("*.json"):
        data = json.loads(cfile.read_text())
        if isinstance(data, list):
            all_constraints.extend(data)
        else:
            all_constraints.append(data)
    return [c for c in all_constraints if c["constraint_id"] in constraint_ids]


# ── Check 1: pytest ───────────────────────────────────────────────────────────

def _run_pytest(repo_path: str, test_filter: str | None = None) -> dict:
    """Run pytest and parse output into a structured result."""
    cmd = [sys.executable, "-m", "pytest", "tests/", "-v",
           "--tb=short", "--json-report", "--json-report-file=/tmp/pytest_report.json"]
    if test_filter:
        cmd += ["-k", test_filter]

    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    # Parse JSON report if available, else parse stdout
    tests_passed = []
    tests_failed = []
    try:
        report = json.loads(Path("/tmp/pytest_report.json").read_text())
        for t in report.get("tests", []):
            name = t["nodeid"]
            if t["outcome"] == "passed":
                tests_passed.append(name)
            else:
                tests_failed.append({"name": name, "reason": t.get("call", {}).get("longrepr", "")[:200]})
    except Exception:
        # Fallback: parse stdout
        for line in result.stdout.splitlines():
            if " PASSED" in line:
                tests_passed.append(line.strip())
            elif " FAILED" in line:
                tests_failed.append({"name": line.strip(), "reason": ""})

    return {
        "passed":       result.returncode == 0,
        "return_code":  result.returncode,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "n_passed":     len(tests_passed),
        "n_failed":     len(tests_failed),
        "stdout":       result.stdout[-2000:] if result.stdout else "",
    }


# ── Check 2: BQ cost constraint ───────────────────────────────────────────────

def _check_bq_cost(repo_path: str, patch_content: str | None) -> dict:
    """
    Dynamically import the (possibly patched) bq_cost_query module
    and check the cost constraint.
    """
    try:
        sys.path.insert(0, repo_path)
        # Force reimport to pick up patched version
        if "bugs.bq_cost_query" in sys.modules:
            del sys.modules["bugs.bq_cost_query"]
        if "bugs.bq_cost_query_fixed" in sys.modules:
            del sys.modules["bugs.bq_cost_query_fixed"]

        # Try patched version first, fall back to fixed reference
        try:
            from bugs.bq_cost_query_fixed import build_order_query, check_cost_constraint
        except ImportError:
            from bugs.bq_cost_query import build_order_query, check_cost_constraint

        query  = build_order_query("COMPLETED", "2024-01-01", "2024-01-31")
        result = check_cost_constraint(query)
        return {
            "constraint_id": "scanned_bytes_below_threshold",
            **result,
        }
    except Exception as e:
        return {
            "constraint_id": "scanned_bytes_below_threshold",
            "passed":        False,
            "error":         str(e),
        }
    finally:
        sys.path.pop(0)


# ── Check 3: Duplicate event constraint ───────────────────────────────────────

def _check_duplicate_event(repo_path: str) -> dict:
    """
    Run the critical retry test against the (possibly patched) pipeline.
    """
    try:
        sys.path.insert(0, repo_path)
        if "bugs.duplicate_event_pipeline" in sys.modules:
            del sys.modules["bugs.duplicate_event_pipeline"]
        if "bugs.duplicate_event_pipeline_fixed" in sys.modules:
            del sys.modules["bugs.duplicate_event_pipeline_fixed"]

        try:
            from bugs.duplicate_event_pipeline_fixed import process_events, Event
        except ImportError:
            from bugs.duplicate_event_pipeline import process_events, Event

        events = [
            Event("evt-retry-001", {"amount": 50}, retry=False),
            Event("evt-retry-001", {"amount": 50}, retry=True),
        ]
        result    = process_events(events)
        retry_ok  = len(result.processed) == 2 and len(result.dropped) == 0

        return {
            "constraint_id":        "no_drop_valid_repeated_events",
            "passed":               retry_ok,
            "events_processed":     len(result.processed),
            "events_dropped":       len(result.dropped),
            "violation": None if retry_ok else (
                f"Retry event was dropped — {len(result.dropped)} events lost. "
                "Constraint: do not drop valid repeated events."
            ),
        }
    except Exception as e:
        return {
            "constraint_id": "no_drop_valid_repeated_events",
            "passed":        False,
            "error":         str(e),
        }
    finally:
        sys.path.pop(0)


# ── Main deliverable ──────────────────────────────────────────────────────────

def verify_patch(
    repo_path: str,
    incident: dict,
    patch_content: str | None = None,
    test_filter: str | None = None,
) -> dict:
    """
    Person A's deliverable B.

    Args:
        repo_path:     path to the toy repo root
        incident:      the incident dict (from incidents/*.json)
        patch_content: optional patch diff text (for static analysis)
        test_filter:   optional pytest -k filter string

    Returns:
        verification_result dict consumed by Person B's Verification Agent
    """
    incident_id     = incident.get("incident_id", "unknown")
    constraint_ids  = incident.get("domain_constraint_ids", [])

    # 1. Run pytest
    pytest_result = _run_pytest(repo_path, test_filter)

    # 2. Run domain constraint checks
    domain_results = []
    for cid in constraint_ids:
        if cid == "scanned_bytes_below_threshold" or cid == "require_partition_filter":
            domain_results.append(_check_bq_cost(repo_path, patch_content))
        elif cid == "no_drop_valid_repeated_events":
            domain_results.append(_check_duplicate_event(repo_path))

    # 3. Aggregate
    all_passed = (
        pytest_result["passed"]
        and all(r.get("passed", False) for r in domain_results)
    )

    blockers = []
    for dr in domain_results:
        if not dr.get("passed") and dr.get("violation"):
            blockers.append(dr["violation"])

    result = {
        "incident_id":      incident_id,
        "passed":           all_passed,
        "blockers":         blockers,
        "pytest":           pytest_result,
        "domain_checks":    domain_results,
        "summary": (
            f"All checks passed"
            if all_passed else
            f"FAILED — {len(blockers)} blocker(s): {'; '.join(blockers[:2])}"
        ),
    }

    return result


# ── CLI runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DebugFlow verifier")
    parser.add_argument("--repo",     default=".", help="path to repo root")
    parser.add_argument("--incident", required=True, help="path to incident JSON")
    parser.add_argument("--out",      default=None, help="output file for result JSON")
    args = parser.parse_args()

    incident = json.loads(Path(args.incident).read_text())
    result   = verify_patch(args.repo, incident)

    output = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(output)
        print(f"Result written to {args.out}")
    else:
        print(output)
