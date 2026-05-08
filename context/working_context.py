"""
context/working_context.py
───────────────────────────
Tier 1 — Working Context (RAM equivalent)

Holds the active state of a single incident investigation:
  • the incident brief
  • the current hypothesis and confidence
  • files currently under inspection
  • the patch draft (once generated)
  • the hypothesis trail  ← NEVER cleared, anti-loop guard
  • token estimate        ← orchestrator pages at 75%

The hypothesis trail is the single most important field.
It records every theory that was ruled out and WHY,
so agents never re-investigate the same dead end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Hypothesis:
    description:      str
    confidence:       float          # 0.0 – 1.0
    status:           str = "active" # active | confirmed | ruled_out
    evidence_for:     list[str] = field(default_factory=list)
    ruled_out_reason: Optional[str] = None
    created_at:       str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def rule_out(self, reason: str) -> None:
        self.status = "ruled_out"
        self.ruled_out_reason = reason

    def confirm(self) -> None:
        self.status = "confirmed"

    def to_dict(self) -> dict:
        return {
            "description":      self.description,
            "confidence":       round(self.confidence, 2),
            "status":           self.status,
            "evidence_for":     self.evidence_for,
            "ruled_out_reason": self.ruled_out_reason,
            "created_at":       self.created_at,
        }


@dataclass
class WorkingContext:
    """
    The live state of one incident investigation.
    Passed between every agent on every turn.
    """
    incident:              dict             = field(default_factory=dict)
    active_hypothesis:     Optional[Hypothesis] = None
    files_under_inspection: list[str]       = field(default_factory=list)
    patch_draft:           Optional[str]    = None
    test_results:          Optional[dict]   = None
    next_action:           str              = "triage"

    # Hypothesis trail — append-only, NEVER paged out
    hypothesis_trail:      list[Hypothesis] = field(default_factory=list)

    # Paging metadata
    turn_count:            int  = 0
    token_estimate:        int  = 0

    # ── Hypothesis management ─────────────────────────────────────────────────

    def add_hypothesis(self, h: Hypothesis) -> None:
        self.hypothesis_trail.append(h)
        if h.status == "active":
            self.active_hypothesis = h

    def rule_out(self, description: str, reason: str) -> bool:
        """Rule out a hypothesis by description. Returns True if found."""
        for h in self.hypothesis_trail:
            if h.description == description and h.status == "active":
                h.rule_out(reason)
                # Promote next active hypothesis
                active = [x for x in self.hypothesis_trail if x.status == "active"]
                self.active_hypothesis = active[0] if active else None
                return True
        return False

    def confirm_hypothesis(self, description: str) -> bool:
        for h in self.hypothesis_trail:
            if h.description == description:
                h.confirm()
                self.active_hypothesis = h
                return True
        return False

    def already_tried(self, description: str) -> bool:
        """
        Anti-loop guard — check if this hypothesis was already ruled out.
        Called before any agent investigates a new theory.
        """
        desc_lower = description.lower()
        for h in self.hypothesis_trail:
            if h.status == "ruled_out":
                if (desc_lower in h.description.lower()
                        or h.description.lower() in desc_lower):
                    return True
        return False

    def get_confirmed(self) -> Optional[Hypothesis]:
        return next(
            (h for h in self.hypothesis_trail if h.status == "confirmed"),
            None,
        )

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "incident_id":          self.incident.get("incident_id"),
            "incident_title":       self.incident.get("title"),
            "severity":             self.incident.get("severity"),
            "active_hypothesis":    self.active_hypothesis.to_dict() if self.active_hypothesis else None,
            "files_under_inspection": self.files_under_inspection,
            "has_patch":            self.patch_draft is not None,
            "patch_preview":        self.patch_draft[:300] if self.patch_draft else None,
            "test_results":         self.test_results,
            "next_action":          self.next_action,
            "hypothesis_trail":     [h.to_dict() for h in self.hypothesis_trail],
            "ruled_out_count":      sum(1 for h in self.hypothesis_trail if h.status == "ruled_out"),
            "turn_count":           self.turn_count,
            "token_estimate":       self.token_estimate,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_incident(cls, incident: dict) -> "WorkingContext":
        """Create a fresh working context from an incident dict."""
        ctx = cls(incident=incident)
        return ctx
