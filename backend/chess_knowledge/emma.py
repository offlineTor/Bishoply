"""Emma persona rendering over shared Bishoply chess facts.

This module contains wording and speech policy only. Chess claims must already
be present in the supplied knowledge/evidence objects.
"""
from __future__ import annotations

import hashlib
from typing import Any

HIGH = {"Blunder", "Mistake", "Miss"}
MEDIUM_TOPICS = {"castle", "give_check", "develop_piece", "center_control", "rook_on_open_file",
                 "passed_pawn", "protected_passed_pawn", "check", "checkmate"}

VARIANTS = {
    "development": [
        "Nice. That brings another piece into the game and helps control the center.",
        "Good progress — another piece is joining the position and supporting the center.",
        "That gets your army moving. Your control of the center is stronger now.",
    ],
    "castling": [
        "Good timing. Your king is safer and your rook can join the game.",
        "That is useful king safety — and it brings the rook closer to the action.",
        "A calm improvement. Your king is tucked away and your rook is connected to the plan.",
    ],
    "center": [
        "Solid. You keep a good grip on the center.",
        "That keeps your central influence healthy.",
        "A useful central choice — your pieces have more room to work.",
    ],
    "material_loss": [
        "Careful. That move gives up material.",
        "Take another look — material is slipping away here.",
        "That costs something concrete. Check the opponent's reply before committing.",
    ],
    "tactics": [
        "You had a tactical chance there. Look for a move that attacks more than one target.",
        "There was a forcing idea available — checks and multiple attacks were worth looking for.",
        "A tactical opportunity passed. Start with the opponent's most valuable targets.",
    ],
    "passed_pawn": [
        "That pawn is becoming important. Keep an eye on its path forward.",
        "Your passer gives you a clear plan: support it and make progress carefully.",
        "The passed pawn is a real asset here. Your king and pieces can help it advance.",
    ],
    "high_swing": [
        "That changes the position sharply. Slow down and check the forcing replies.",
        "This is a serious turn in the game. Look first for checks, captures, and threats.",
        "The position has swung. Practical activity is important now — do not drift passively.",
    ],
    "routine": [
        "A steady move.",
        "That keeps the position together.",
        "A calm, useful choice.",
    ],
}


def _pick(topic: str, game_id: str | None, ply: int | None, state: str | None) -> str:
    options = VARIANTS.get(topic, VARIANTS["routine"])
    seed = f"{game_id or 'game'}:{ply or 0}:{topic}:{state or 'none'}".encode()
    return options[int.from_bytes(hashlib.sha256(seed).digest()[:4], "big") % len(options)]


def _facts(knowledge: dict) -> tuple[set[str], set[str], list[dict]]:
    motifs = knowledge.get("tactical_motifs", []) or []
    purposes = knowledge.get("move_purpose", []) or []
    return ({str(m.get("type")) for m in motifs}, {str(p.get("type")) for p in purposes}, motifs + purposes)


def compose_emma(*, classification: str | None, knowledge: dict | None = None,
                 evaluation: dict | None = None, context: dict | None = None,
                 game_id: str | None = None, ply: int | None = None) -> dict[str, Any]:
    """Return the final compact Emma message and speech decision."""
    knowledge = knowledge or {}
    context = context or {}
    motifs, purposes, evidence = _facts(knowledge)
    phase = knowledge.get("phase", "middlegame")
    issues = context.get("issue_states", {})
    repeated = [key for key, state in issues.items() if state == "repeated"]
    resolved = [key for key, state in issues.items() if state == "resolved"]
    returned = [key for key, state in issues.items() if state == "returned"]
    topic = "routine"
    priority = "low"
    message = None
    issue_state = None
    if classification in HIGH:
        priority, topic = "high", "tactics" if motifs else "material_loss" if "win_material" in purposes else "high_swing"
        message = _pick(topic, game_id, ply, None)
    elif repeated:
        issue_state, priority, topic = "repeated", "high", "development" if "delayed_development" in repeated else "tactics"
        message = ("That development issue is showing up again." if topic == "development" else
                   "That same tactical issue is showing up again.")
    elif returned:
        issue_state, priority, topic = "returned", "high", "development"
        message = "That same issue has come back — your pieces are falling behind again."
    elif resolved:
        issue_state, priority, topic = "resolved", "medium", "development" if "delayed_development" in resolved else "routine"
        message = "Better. Your pieces are finally getting into the game." if topic == "development" else "Better — you corrected the earlier issue."
    elif "castle" in purposes:
        priority, topic, message = "medium", "castling", _pick("castling", game_id, ply, None)
    elif "develop_piece" in purposes:
        priority, topic, message = "medium", "development", _pick("development", game_id, ply, None)
    elif "center_control" in purposes or "occupy_center" in purposes:
        priority, topic, message = "medium", "center", _pick("center", game_id, ply, None)
    elif "protected_passed_pawn" in {p.get("type") for p in knowledge.get("pawn_features", [])} or "passed_pawn" in purposes:
        priority, topic, message = "medium", "passed_pawn", _pick("passed_pawn", game_id, ply, None)
    elif "check" in motifs:
        priority, topic, message = "medium", "tactics", "That check is forcing — make sure you know what it changes."
    elif classification in {"Best", "Excellent"} and phase != "opening":
        priority, topic, message = "low", "routine", _pick("routine", game_id, ply, None)
    # Routine Good moves intentionally remain silent.
    if priority == "low" and classification not in {"Best", "Excellent"}:
        message = None
    should_comment = bool(message)
    should_speak = should_comment and (priority == "high" or (priority == "medium" and classification in {"Best", "Excellent", "Check"}))
    return {"should_comment": should_comment, "should_speak": should_speak,
            "priority": priority, "topic": topic, "issue_state": issue_state,
            "message": message, "supporting_facts": evidence,
            "message_key": f"{game_id or 'game'}:{ply or 0}:{topic}:{message or ''}"}


def game_summary(*, context: dict | None = None, phase: str | None = None,
                 game_id: str | None = None) -> dict[str, Any]:
    context = context or {}
    counters = context.get("issue_counters", {})
    recurring = [key for key, count in counters.items() if count >= 2]
    if recurring:
        label = recurring[0].replace("_", " ")
        message = f"The game was shaped by a recurring {label} issue."
    elif phase:
        message = f"You handled the {phase} with a steady plan."
    else:
        message = None
    return {"message": message, "recurring_issues": recurring,
            "evidence": {"issue_counters": counters, "phase": phase},
            "should_comment": bool(message)}
