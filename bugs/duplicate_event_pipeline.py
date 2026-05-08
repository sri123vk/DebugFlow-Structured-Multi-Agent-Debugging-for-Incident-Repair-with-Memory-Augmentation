"""
bugs/duplicate_event_pipeline.py
─────────────────────────────────
Event deduplication pipeline.

BUG: uses a plain set() for seen_ids. This means if the same event
arrives twice (a valid retry after a transient failure), the second
delivery is silently dropped instead of being processed.

The domain constraint says: "Do not drop valid repeated events."
A correct implementation must distinguish between true duplicates
(same event_id AND same payload) and retries (same event_id but
the first delivery was never acknowledged / committed).

The fix: track (event_id, ack_status) rather than just event_id,
OR use a time-windowed dedup that expires seen IDs after the
retry window closes.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    event_id: str
    payload: dict[str, Any]
    retry: bool = False          # True if this is a re-delivery


@dataclass
class PipelineResult:
    processed: list[Event] = field(default_factory=list)
    dropped:   list[Event] = field(default_factory=list)


def process_events(events: list[Event]) -> PipelineResult:
    """
    Process a stream of events, deduplicating by event_id.

    BUG: a plain set deduplicates by event_id alone.
    Retry events (same event_id, retry=True) are silently dropped
    even though they should be processed — the original may not
    have been committed.
    """
    result   = PipelineResult()
    seen_ids: set[str] = set()          # BUG: too aggressive — drops retries

    for event in events:
        if event.event_id in seen_ids:
            result.dropped.append(event)  # silently drops valid retries
        else:
            seen_ids.add(event.event_id)
            result.processed.append(event)

    return result
