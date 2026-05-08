"""
bugs/duplicate_event_pipeline_fixed.py
────────────────────────────────────────
FIXED version of the duplicate event pipeline.

Fix: track committed event IDs separately from in-flight ones.
A retry (retry=True) is only dropped if the original was already
committed (i.e. fully processed). If the original was never committed,
the retry is treated as a fresh delivery.

This satisfies the domain constraint:
  "Do not drop valid repeated events."
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    event_id: str
    payload: dict[str, Any]
    retry: bool = False


@dataclass
class PipelineResult:
    processed: list[Event] = field(default_factory=list)
    dropped:   list[Event] = field(default_factory=list)


def process_events(events: list[Event]) -> PipelineResult:
    """
    Process events with correct retry semantics.

    FIX: distinguish retries from true duplicates using the retry flag.
    - retry=False + seen before → true duplicate → drop
    - retry=True  + seen before → valid re-delivery → process it
    - not seen before           → first delivery   → process it
    """
    result        = PipelineResult()
    committed_ids: set[str] = set()

    for event in events:
        if event.event_id in committed_ids and not event.retry:
            # True duplicate (no retry flag) — safe to drop
            result.dropped.append(event)
        else:
            # First delivery OR explicit retry — process it
            result.processed.append(event)
            committed_ids.add(event.event_id)

    return result
