"""
context/recall_storage.py
──────────────────────────
Tier 2 — Recall Storage (SSD equivalent)

Stores the full session log for ONE incident.
Every agent turn, tool output, and ruled-out hypothesis
is written here as a RecallEntry.

Key properties:
  • Scoped per incident_id — one incident cannot read another's recall
  • Searchable by keyword similarity (no external vector DB needed)
  • Entries are timestamped and tagged by which agent wrote them
  • Cleared (TTL) after incident resolves — does NOT persist to archival
  • Only VALIDATED results are written to archival by the memory manager

Backed by a JSON file on disk so it survives process restarts
and can be inspected by humans during debugging.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Entry model ───────────────────────────────────────────────────────────────

@dataclass
class RecallEntry:
    incident_id: str
    agent:       str                      # which agent wrote this
    content:     str                      # the actual text content
    tags:        list[str] = field(default_factory=list)
    timestamp:   str = field(default_factory=lambda: datetime.utcnow().isoformat())
    entry_id:    str = field(default_factory=lambda: datetime.utcnow().strftime("%Y%m%d%H%M%S%f"))

    def to_dict(self) -> dict:
        return {
            "entry_id":    self.entry_id,
            "incident_id": self.incident_id,
            "agent":       self.agent,
            "content":     self.content,
            "tags":        self.tags,
            "timestamp":   self.timestamp,
        }


# ── Keyword search ────────────────────────────────────────────────────────────

def _keyword_score(query: str, text: str) -> float:
    """Simple term overlap score — no external deps needed."""
    q_terms = set(re.findall(r"\w+", query.lower()))
    t_terms = set(re.findall(r"\w+", text.lower()))
    if not q_terms:
        return 0.0
    return len(q_terms & t_terms) / len(q_terms)


# ── Recall store ──────────────────────────────────────────────────────────────

class RecallStorage:
    """
    Per-incident session log with keyword search.

    Usage:
        recall = RecallStorage(store_dir="memory/recall")
        recall.write(RecallEntry(incident_id="INC-001", agent="triage",
                                 content="...", tags=["hypothesis"]))
        hits = recall.search("INC-001", "null pointer config loader", top_k=5)
    """

    def __init__(self, store_dir: str = "memory/recall") -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, incident_id: str) -> Path:
        """One JSON file per incident."""
        safe = incident_id.replace("/", "_").replace(" ", "_")
        return self.store_dir / f"{safe}.json"

    def _load(self, incident_id: str) -> list[dict]:
        p = self._path(incident_id)
        if not p.exists():
            return []
        return json.loads(p.read_text())

    def _save(self, incident_id: str, entries: list[dict]) -> None:
        self._path(incident_id).write_text(json.dumps(entries, indent=2))

    # ── Write ─────────────────────────────────────────────────────────────────

    def write(self, entry: RecallEntry) -> None:
        """Append one entry to this incident's session log."""
        entries = self._load(entry.incident_id)
        entries.append(entry.to_dict())
        self._save(entry.incident_id, entries)

    def write_many(self, entries: list[RecallEntry]) -> None:
        for e in entries:
            self.write(e)

    # ── Read / search ─────────────────────────────────────────────────────────

    def search(
        self,
        incident_id: str,
        query: str,
        top_k: int = 5,
        tag_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic-style keyword search over this incident's session log.
        Returns top_k most relevant entries as dicts with a 'score' field.
        """
        entries = self._load(incident_id)
        if not entries:
            return []

        scored = []
        for e in entries:
            if tag_filter and tag_filter not in e.get("tags", []):
                continue
            text  = e.get("content", "") + " " + " ".join(e.get("tags", []))
            score = _keyword_score(query, text)
            if score > 0:
                scored.append({**e, "score": round(score, 3)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def get_all(self, incident_id: str) -> list[dict]:
        """Return the full session log for an incident, chronological."""
        return self._load(incident_id)

    def get_by_tag(self, incident_id: str, tag: str) -> list[dict]:
        return [e for e in self._load(incident_id) if tag in e.get("tags", [])]

    def get_hypothesis_trail(self, incident_id: str) -> list[dict]:
        """Retrieve all hypothesis-related entries."""
        return self.get_by_tag(incident_id, "hypothesis")

    def already_tried(self, incident_id: str, description: str) -> Optional[str]:
        """
        Check if a hypothesis was already ruled out in this session.
        Returns the reason it was ruled out, or None if not tried.
        """
        ruled_out = self.get_by_tag(incident_id, "ruled_out")
        desc_lower = description.lower()
        for e in ruled_out:
            if desc_lower in e["content"].lower():
                return e["content"]
        return None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def clear(self, incident_id: str) -> None:
        """TTL equivalent — clear session after incident resolves."""
        p = self._path(incident_id)
        if p.exists():
            p.unlink()

    def count(self, incident_id: str) -> int:
        return len(self._load(incident_id))

    def summary(self, incident_id: str) -> dict:
        entries = self._load(incident_id)
        agents  = {}
        for e in entries:
            agents[e.get("agent", "?")] = agents.get(e.get("agent", "?"), 0) + 1
        return {
            "incident_id": incident_id,
            "total_entries": len(entries),
            "entries_by_agent": agents,
            "tags": list({t for e in entries for t in e.get("tags", [])}),
        }
