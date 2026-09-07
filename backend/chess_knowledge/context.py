"""Bounded, persona-independent context for evidence-backed coaching."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

ISSUES = ("repeated_queen_moves", "delayed_development", "king_uncastled",
          "hanging_piece_errors", "missed_tactics", "repeated_material_loss",
          "pawn_weaknesses", "ignored_threats")


@dataclass
class CoachContext:
    """Bounded game context. It stores facts, not persona wording."""
    max_moves: int = 6
    recent_moves: deque = field(default_factory=lambda: deque(maxlen=6))
    recent_classifications: deque = field(default_factory=lambda: deque(maxlen=6))
    recent_motifs: deque = field(default_factory=lambda: deque(maxlen=6))
    recent_strategic_topics: deque = field(default_factory=lambda: deque(maxlen=6))
    issue_counters: dict[str, int] = field(default_factory=lambda: {key: 0 for key in ISSUES})
    issue_states: dict[str, str] = field(default_factory=dict)
    corrections: dict[str, int] = field(default_factory=dict)
    previous_coach_topic: str | None = None
    previous_warning: str | None = None
    last_spoken_ply: int | None = None

    def __post_init__(self):
        for name in ISSUES:
            self.issue_counters.setdefault(name, 0)
        self.recent_moves = deque(self.recent_moves, maxlen=self.max_moves)
        self.recent_classifications = deque(self.recent_classifications, maxlen=self.max_moves)
        self.recent_motifs = deque(self.recent_motifs, maxlen=self.max_moves)
        self.recent_strategic_topics = deque(self.recent_strategic_topics, maxlen=self.max_moves)

    def update(self, *, ply: int, move: str | None = None, classification: str | None = None,
               knowledge: dict | None = None, coach_topic: str | None = None,
               warning: str | None = None, spoken: bool = False) -> dict[str, Any]:
        knowledge = knowledge or {}
        motifs = [m.get("type") for m in knowledge.get("tactical_motifs", []) if m.get("type")]
        topics = list(knowledge.get("coaching_topics", []))
        self.recent_moves.append({"ply": ply, "move": move})
        self.recent_classifications.append({"ply": ply, "classification": classification})
        self.recent_motifs.append({"ply": ply, "motifs": motifs})
        self.recent_strategic_topics.append({"ply": ply, "topics": topics})
        detected = set()
        if classification in {"Mistake", "Blunder", "Miss"} and any(x in motifs for x in ("fork", "double_attack", "discovered_attack", "checkmate")):
            detected.add("missed_tactics")
        if classification in {"Mistake", "Blunder"} and any(x in topics for x in ("win_material",)):
            detected.add("repeated_material_loss")
        if "develop_piece" not in topics and ply <= 16:
            detected.add("delayed_development")
        safety = knowledge.get("king_safety", {}).get(knowledge.get("side_to_move", "white"), {})
        if safety and not safety.get("castled") and ply >= 10:
            detected.add("king_uncastled")
        pawn_types = {p.get("type") for p in knowledge.get("pawn_features", [])}
        if pawn_types & {"isolated_pawn", "doubled_pawn", "tripled_pawn", "backward_pawn"}:
            detected.add("pawn_weaknesses")
        for issue in ISSUES:
            if issue in detected:
                old = self.issue_states.get(issue)
                self.issue_counters[issue] += 1
                self.issue_states[issue] = "returned" if old == "resolved" else ("repeated" if old in {"detected", "repeated", "returned"} else "detected")
            elif self.issue_states.get(issue) in {"detected", "repeated", "returned"}:
                self.issue_states[issue] = "resolved"
                self.corrections[issue] = self.corrections.get(issue, 0) + 1
        if coach_topic:
            self.previous_coach_topic = coach_topic
        if warning:
            self.previous_warning = warning
        if spoken:
            self.last_spoken_ply = ply
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {"recent_moves": list(self.recent_moves),
                "recent_classifications": list(self.recent_classifications),
                "recent_motifs": list(self.recent_motifs),
                "recent_strategic_topics": list(self.recent_strategic_topics),
                "issue_counters": dict(self.issue_counters),
                "issue_states": dict(self.issue_states),
                "corrections": dict(self.corrections),
                "previous_coach_topic": self.previous_coach_topic,
                "previous_warning": self.previous_warning,
                "last_spoken_ply": self.last_spoken_ply,
                "bounded": True}

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "CoachContext":
        if not value:
            return cls()
        return cls(max_moves=min(6, int(value.get("max_moves", 6))), **{
            key: deepcopy(value.get(key, [])) for key in
            ("recent_moves", "recent_classifications", "recent_motifs", "recent_strategic_topics")
        }, issue_counters=dict(value.get("issue_counters", {})),
            issue_states=dict(value.get("issue_states", {})), corrections=dict(value.get("corrections", {})),
            previous_coach_topic=value.get("previous_coach_topic"), previous_warning=value.get("previous_warning"),
            last_spoken_ply=value.get("last_spoken_ply"))
