"""
tests/test_duplicate_pipeline.py
──────────────────────────────────
Pytest tests for the duplicate event pipeline.

Tests cover:
  - Normal deduplication (true duplicate should be dropped)
  - Retry of uncommitted event (must NOT be dropped — domain constraint)
  - Mixed stream with both duplicates and retries
  - Empty stream edge case
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ── Test the BUGGY version first (to confirm it fails) ────────────────────────

class TestBuggyPipeline:
    """These tests document what the buggy version does wrong."""

    def test_normal_dedup_passes_in_buggy(self):
        """True duplicate should be dropped — buggy version gets this right."""
        from bugs.duplicate_event_pipeline import process_events, Event

        events = [
            Event("evt-001", {"amount": 100}),
            Event("evt-001", {"amount": 100}),   # true duplicate
        ]
        result = process_events(events)
        assert len(result.processed) == 1
        assert len(result.dropped)   == 1

    def test_retry_dropped_in_buggy(self):
        """
        Retry of an uncommitted event is WRONGLY dropped by the buggy version.
        This test PASSES (confirms the bug exists) — it documents the failure.
        """
        from bugs.duplicate_event_pipeline import process_events, Event

        events = [
            Event("evt-002", {"amount": 50}, retry=False),
            Event("evt-002", {"amount": 50}, retry=True),   # retry — should be kept
        ]
        result = process_events(events)
        # Buggy: retry is dropped
        assert len(result.dropped) == 1
        assert result.dropped[0].retry is True


# ── Test the FIXED version ────────────────────────────────────────────────────

class TestFixedPipeline:
    """These are the real passing tests — verify the fix is correct."""

    def test_true_duplicate_is_dropped(self):
        """True duplicate (no retry flag) must still be deduplicated."""
        from bugs.duplicate_event_pipeline_fixed import process_events, Event

        events = [
            Event("evt-001", {"amount": 100}),
            Event("evt-001", {"amount": 100}),
        ]
        result = process_events(events)
        assert len(result.processed) == 1
        assert len(result.dropped)   == 1

    def test_retry_of_uncommitted_is_processed(self):
        """
        Domain constraint: do not drop valid repeated events.
        A retry must be processed, not silently dropped.
        """
        from bugs.duplicate_event_pipeline_fixed import process_events, Event

        events = [
            Event("evt-002", {"amount": 50}, retry=False),
            Event("evt-002", {"amount": 50}, retry=True),   # retry — keep it
        ]
        result = process_events(events)
        assert len(result.processed) == 2, (
            "Retry of uncommitted event must be processed — "
            "domain constraint: do not drop valid repeated events"
        )
        assert len(result.dropped) == 0

    def test_mixed_stream(self):
        """Mixed stream: some true duplicates, some retries."""
        from bugs.duplicate_event_pipeline_fixed import process_events, Event

        events = [
            Event("evt-A", {"val": 1}),                      # first delivery
            Event("evt-B", {"val": 2}),                      # first delivery
            Event("evt-A", {"val": 1}, retry=True),          # retry of A
            Event("evt-B", {"val": 2}),                      # true duplicate of B
            Event("evt-C", {"val": 3}),                      # new event
        ]
        result = process_events(events)
        # evt-A: processed (first) + processed (retry) = 2
        # evt-B: processed (first) + dropped (true dup) = 1 processed + 1 dropped
        # evt-C: processed = 1
        assert len(result.processed) == 4
        assert len(result.dropped)   == 1

    def test_empty_stream(self):
        from bugs.duplicate_event_pipeline_fixed import process_events, Event
        result = process_events([])
        assert result.processed == []
        assert result.dropped   == []

    def test_all_unique(self):
        from bugs.duplicate_event_pipeline_fixed import process_events, Event
        events = [Event(f"evt-{i}", {"val": i}) for i in range(10)]
        result = process_events(events)
        assert len(result.processed) == 10
        assert len(result.dropped)   == 0
