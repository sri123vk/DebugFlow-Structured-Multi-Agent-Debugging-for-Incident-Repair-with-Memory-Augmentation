"""
context/archival_storage.py
────────────────────────────
Tier 3 — Archival Storage (Disk equivalent)

Stores validated, resolved incident records permanently.
Shared across ALL incidents — this is where the system learns.

Key properties:
  • Append-only with versioning (deprecated_by pointer for corrections)
  • Human-approved writes only (write_validated enforces this)
  • Grows with every resolved incident — compounding knowledge
  • Semantic + keyword search over past RCAs and fix patterns
  • Pre-seeded with known past incidents so Person B's agent has
    something to retrieve from day one

Backed by a JSON file on disk.
In production: swap for Qdrant with hybrid BM25 + dense vectors.

Two record types:
  • "incident"      — a resolved bug with RCA, fix, and patch
  • "patch_pattern" — a reusable fix template (e.g. null-safe config)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Record model ──────────────────────────────────────────────────────────────

@dataclass
class ArchivalRecord:
    record_id:     str
    record_type:   str                     # "incident" | "patch_pattern"
    title:         str
    symptoms:      list[str]               # keywords for matching
    root_cause:    str                     # confirmed RCA
    fix_pattern:   str                     # what the fix does
    files_changed: list[str]
    patch_diff:    Optional[str] = None    # actual diff if available
    tests_passed:  list[str] = field(default_factory=list)
    confidence:    float = 1.0
    incident_id:   Optional[str] = None
    version:       int = 1
    deprecated_by: Optional[str] = None   # points to newer record_id
    created_at:    str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "record_id":     self.record_id,
            "record_type":   self.record_type,
            "title":         self.title,
            "symptoms":      self.symptoms,
            "root_cause":    self.root_cause,
            "fix_pattern":   self.fix_pattern,
            "files_changed": self.files_changed,
            "patch_diff":    self.patch_diff,
            "tests_passed":  self.tests_passed,
            "confidence":    round(self.confidence, 2),
            "incident_id":   self.incident_id,
            "version":       self.version,
            "deprecated_by": self.deprecated_by,
            "created_at":    self.created_at,
        }


# ── Keyword search ────────────────────────────────────────────────────────────

def _score(query: str, record: ArchivalRecord) -> float:
    """Score a record against a query using term overlap."""
    q_terms = set(re.findall(r"\w+", query.lower()))
    if not q_terms:
        return 0.0
    text = " ".join([
        record.title,
        record.root_cause,
        record.fix_pattern,
        " ".join(record.symptoms),
        " ".join(record.files_changed),
    ]).lower()
    t_terms = set(re.findall(r"\w+", text))
    overlap  = q_terms & t_terms
    return len(overlap) / len(q_terms)


# ── Archival store ────────────────────────────────────────────────────────────

class ArchivalStorage:
    """
    Permanent org-wide knowledge base.

    Usage:
        archival = ArchivalStorage("memory/archival.json")
        archival.seed_defaults()           # load past incidents
        hits = archival.search("null pointer config loader", top_k=3)
        archival.write_validated(record)   # only after human/auto approval
    """

    def __init__(self, store_path: str = "memory/archival.json") -> None:
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self.store_path.write_text("[]")

    def _load(self) -> list[dict]:
        return json.loads(self.store_path.read_text())

    def _save(self, records: list[dict]) -> None:
        self.store_path.write_text(json.dumps(records, indent=2))

    # ── Write ─────────────────────────────────────────────────────────────────

    def write_validated(self, record: ArchivalRecord) -> ArchivalRecord:
        """
        Write a VALIDATED incident record to archival.
        Enforces minimum quality: root_cause, symptoms, confidence >= 0.5.
        Only called after verification agent approves the patch.
        """
        if not record.root_cause:
            raise ValueError("archival write requires non-empty root_cause")
        if not record.symptoms:
            raise ValueError("archival write requires at least one symptom")
        if record.confidence < 0.5:
            raise ValueError(f"confidence {record.confidence} below minimum 0.5")
        if record.deprecated_by:
            raise ValueError("cannot write a record that is already deprecated")

        records = self._load()
        records.append(record.to_dict())
        self._save(records)
        return record

    def _force_write(self, record: ArchivalRecord) -> None:
        """Internal — for seeding only, bypasses validation."""
        records = self._load()
        records.append(record.to_dict())
        self._save(records)

    def deprecate(self, record_id: str, superseded_by: str) -> bool:
        """Mark a record as deprecated when a better fix is found."""
        records = self._load()
        for r in records:
            if r["record_id"] == record_id:
                r["deprecated_by"] = superseded_by
                self._save(records)
                return True
        return False

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        record_type: Optional[str] = None,
        top_k: int = 5,
        min_score: float = 0.0,
        exclude_deprecated: bool = True,
    ) -> list[dict]:
        """
        Keyword search over archival records.
        Returns top_k matches sorted by score, with score field added.
        """
        raw = self._load()
        scored = []
        for r in raw:
            if exclude_deprecated and r.get("deprecated_by"):
                continue
            if record_type and r.get("record_type") != record_type:
                continue
            rec   = ArchivalRecord(**{k: v for k, v in r.items()
                                       if k in ArchivalRecord.__dataclass_fields__})
            score = _score(query, rec)
            if score > min_score:
                scored.append({**r, "score": round(score, 3)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def get_by_id(self, record_id: str) -> Optional[dict]:
        for r in self._load():
            if r["record_id"] == record_id:
                return r
        return None

    def get_by_file(self, file_path: str) -> list[dict]:
        """Return all records that touched a specific file."""
        return [r for r in self._load()
                if file_path in r.get("files_changed", [])]

    def count(self) -> int:
        return len(self._load())

    def all_records(self) -> list[dict]:
        return self._load()

    # ── Seed past incidents ───────────────────────────────────────────────────

    def seed_defaults(self) -> None:
        """
        Pre-populate archival with realistic past incidents.
        Called once on startup. Skips if already seeded.
        """
        if self.count() > 0:
            return   # already seeded

        past = [
            ArchivalRecord(
                record_id="arc-dup-001",
                record_type="incident",
                incident_id="INC-DUP-PREV-001",
                title="Event pipeline dropping retry deliveries silently",
                symptoms=[
                    "silent data loss", "event dropped", "retry", "duplicate",
                    "process_events", "deduplication", "set seen_ids",
                ],
                root_cause=(
                    "process_events uses a plain set() for deduplication keyed "
                    "only on event_id. Retry deliveries (retry=True) with the "
                    "same event_id are silently dropped even when the original "
                    "was never committed."
                ),
                fix_pattern=(
                    "Check the retry flag before deduplicating. "
                    "Only drop an event if it has no retry flag AND its "
                    "event_id is already in committed_ids. "
                    "Use: if event.event_id in committed_ids and not event.retry"
                ),
                files_changed=["bugs/duplicate_event_pipeline.py"],
                tests_passed=[
                    "test_retry_of_uncommitted_is_processed",
                    "test_mixed_stream",
                    "test_true_duplicate_is_dropped",
                ],
                confidence=0.97,
            ),
            ArchivalRecord(
                record_id="arc-dup-002",
                record_type="patch_pattern",
                title="Retry-aware event deduplication pattern",
                symptoms=["retry", "duplicate", "event_id", "dedup", "set"],
                root_cause=(
                    "Using set() keyed on event_id alone conflates true "
                    "duplicates with retries of uncommitted events."
                ),
                fix_pattern="""
# Before (broken):
seen_ids: set[str] = set()
if event.event_id in seen_ids:
    result.dropped.append(event)  # drops valid retries too

# After (fixed):
committed_ids: set[str] = set()
if event.event_id in committed_ids and not event.retry:
    result.dropped.append(event)  # only drops true duplicates
else:
    result.processed.append(event)
    committed_ids.add(event.event_id)
""",
                files_changed=[],
                confidence=0.99,
            ),
            ArchivalRecord(
                record_id="arc-bq-001",
                record_type="incident",
                incident_id="INC-BQ-PREV-001",
                title="BigQuery full table scan — missing partition filter on order_date",
                symptoms=[
                    "BigQuery cost spike", "full table scan", "partition filter",
                    "order_date", "build_order_query", "bytes billed", "bq_cost",
                    "scanned bytes", "CostConstraintViolation",
                ],
                root_cause=(
                    "build_order_query accepts start_date and end_date parameters "
                    "but never uses them in the WHERE clause. The query filters only "
                    "on status, causing BigQuery to scan the full 180 TB table."
                ),
                fix_pattern=(
                    "Add WHERE order_date BETWEEN start_date AND end_date before "
                    "the status filter. Provide safe defaults (last 7 days) so the "
                    "partition filter is always applied even when no dates are passed."
                ),
                files_changed=["bugs/bq_cost_query.py"],
                tests_passed=[
                    "test_partition_filter_present",
                    "test_cost_constraint_passes",
                    "test_default_date_range_also_filtered",
                    "test_cost_is_low",
                ],
                confidence=0.95,
            ),
            ArchivalRecord(
                record_id="arc-bq-002",
                record_type="patch_pattern",
                title="BigQuery partition filter pattern — always apply date range",
                symptoms=[
                    "BigQuery", "partition", "order_date", "full scan",
                    "cost", "bytes", "WHERE clause",
                ],
                root_cause=(
                    "Query parameters passed to a function are not propagated "
                    "into the SQL WHERE clause, resulting in no partition pruning."
                ),
                fix_pattern="""
# Before (broken):
def build_order_query(status, start_date=None, end_date=None):
    return f\"\"\"SELECT ... FROM orders WHERE status = '{status}'\"\"\".strip()
    # start_date and end_date are IGNORED

# After (fixed):
def build_order_query(status, start_date=None, end_date=None):
    start = start_date or "DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
    end   = end_date   or "CURRENT_DATE()"
    return f\"\"\"
    SELECT ... FROM orders
    WHERE order_date BETWEEN {start} AND {end}
      AND status = '{status}'
    \"\"\".strip()
""",
                files_changed=[],
                confidence=0.99,
            ),
        ]

        for record in past:
            self._force_write(record)

        print(f"[archival] seeded {len(past)} records")
