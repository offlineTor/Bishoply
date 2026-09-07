"""Canonical Bishoply Intelligence V1 representations and scoring.

All engine values entering this module use integer E2000 units (0..2000),
where 2000 is a certain win for the requested perspective and 0 is a loss.
This preserves the existing Stockfish WDL signal and avoids floating-point
boundary decisions.  Public display may use pawns, but classification never
does.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from . import config as C

SCHEMA_VERSION = "bishoply-intelligence-v1"
ACCURACY_VERSION = "bishoply-move-accuracy-v1-wdl"
GAME_ACCURACY_VERSION = "bishoply-game-accuracy-v1-volatility"

@dataclass(frozen=True)
class CanonicalEvaluation:
    cp: int | None
    mate: int | None
    wdl: tuple[int, int, int] | None
    outcome_units: int
    perspective: str

    @property
    def win_probability(self) -> float:
        return self.outcome_units / 2000

    @property
    def pawns(self) -> float | None:
        return None if self.cp is None else self.cp / 100

    def as_dict(self):
        return {**asdict(self), "wdl": list(self.wdl) if self.wdl else None,
                "pawns": self.pawns, "win_probability": self.win_probability}

def canonical_evaluation(raw: dict, *, perspective: str | None = None) -> CanonicalEvaluation:
    units = raw.get("outcome_units")
    if type(units) is not int or not 0 <= units <= 2000:
        raise ValueError("canonical outcome_units must be an integer in [0,2000]")
    wdl = raw.get("wdl")
    if wdl is not None:
        wdl = tuple(wdl)
    return CanonicalEvaluation(raw.get("cp"), raw.get("mate"), wdl, units,
                               perspective or raw.get("perspective", "side_to_move"))

def player_perspective_units(evaluation: dict, player_color: str) -> int:
    """Convert an explicitly white/black evaluation to player's outcome."""
    units = canonical_evaluation(evaluation).outcome_units
    perspective = evaluation.get("perspective")
    if perspective not in ("white", "black"):
        raise ValueError("evaluation perspective must be explicitly white or black")
    if perspective == player_color:
        return units
    return 2000 - units

def opportunity_loss(best: dict, played: dict, *, forced: bool = False) -> int:
    if forced:
        return 0
    # Both candidates are scored from the same side-to-move root.
    return max(0, canonical_evaluation(best).outcome_units - canonical_evaluation(played).outcome_units)

def move_accuracy(loss_units: int, *, forced: bool = False, book: bool = False,
                  mate_transition: str | None = None) -> int | None:
    if forced or book:
        return None
    if type(loss_units) is not int or not 0 <= loss_units <= 2000:
        raise ValueError("loss_units must be an integer in [0,2000]")
    if mate_transition == "lost":
        loss_units = max(loss_units, C.MATE_LOSS_FLOOR)
    # Versioned WDL-derived exponential: 0 loss=100; 2000 loss approaches 0.
    return max(0, min(100, round(100 * math.exp(-4 * loss_units / 2000))))

def game_accuracy(moves: list[dict]) -> dict:
    """Aggregate move accuracy with decision weighting and volatility control."""
    rows = [m for m in moves if m.get("move_accuracy") is not None and not m.get("forced_move") and not m.get("book") and not m.get("assisted")]
    if not rows:
        return {"value": None, "included_moves": 0, "game_accuracy_model_version": GAME_ACCURACY_VERSION}
    weights = []
    scores = []
    for row in rows:
        before = int(row.get("evaluation_before", {}).get("outcome_units", 1000))
        decided = before <= C.DECIDED_LOW or before >= C.DECIDED_HIGH
        weight = 0.25 if decided else 0.5 if row.get("forced_tactical") else 1.0
        weights.append(weight)
        scores.append(row["move_accuracy"])
    mean = sum(s*w for s,w in zip(scores, weights)) / sum(weights)
    harmonic = sum(weights) / sum(w / max(1.0, s) for s, w in zip(scores, weights))
    # Volatility dampens a high average when a game contains a large swing.
    losses = [int(r.get("loss_units", 0)) for r in rows]
    volatility = min(1.0, (max(losses) / 2000) if losses else 0.0)
    blended = (mean + harmonic) / 2
    value = round(max(0.0, blended * (1 - 0.12 * volatility)), 1)
    return {"value": value, "included_moves": len(rows), "weight": sum(weights),
            "arithmetic_mean": round(mean, 1), "harmonic_mean": round(harmonic, 1), "volatility": round(volatility, 3),
            "game_accuracy_model_version": GAME_ACCURACY_VERSION}

def intelligence_result(*, ply, move_uci, move_san, fen_before, fen_after,
                        evaluation_before, evaluation_after, best_move, candidates,
                        loss_units, classification, forced_move=False, book=False,
                        concepts=None, threats=None, hint=None, coach=None,
                        knowledge=None, preliminary=False, verification_occurred=False,
                        provenance=None):
    transition = (evaluation_after.get("mate_policy") or {}).get("transition") if isinstance(evaluation_after, dict) else None
    return {
        "schema_version": SCHEMA_VERSION, "ply": ply, "move_uci": move_uci,
        "move_san": move_san, "fen_before": fen_before, "fen_after": fen_after,
        "evaluation": canonical_evaluation(evaluation_after).as_dict(),
        "evaluation_before": evaluation_before, "evaluation_after": evaluation_after,
        "move_quality": {"win_probability_before": canonical_evaluation(evaluation_before).win_probability,
            "win_probability_after": canonical_evaluation(evaluation_after).win_probability,
            "win_probability_loss": loss_units / 2000,
            "move_accuracy": move_accuracy(loss_units, forced=forced_move, book=book, mate_transition=transition),
            "classification": classification},
        "best_move": best_move, "candidates": candidates, "concepts": concepts or [],
        "threats": threats or [], "hint": hint, "coach": coach or {},
        "knowledge": knowledge,
        "provenance": {**(provenance or {}), "accuracy_version": ACCURACY_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(), "preliminary": preliminary,
            "verification_occurred": verification_occurred},
    }
