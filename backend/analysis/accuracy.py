"""Experimental, opportunity-weighted RMS loss. No claim of human calibration.
Forced/Book/assisted decisions have weight zero. Already decided positions have
zero weight if they remain decided and lose <=40 units; otherwise weight 1/4.
In-check forced tactical responses use weight 1/2. Other decisions use weight 1.
Mate preservation/shortening/lengthening are excluded; losing a forced mate uses
max(opportunity loss, 360 units). Equal dead moves cannot dilute the denominator.
"""
import math
from . import config as C


def measure(moves):
    total = weighted = 0.0
    included = 0
    for move in moves:
        if move.get("forced_move") or move.get("book") or move.get("assisted"):
            continue
        transition = move.get("mate_policy", {}).get("transition")
        if transition in ("preserved", "shortened", "lengthened", "terminal_checkmate"):
            continue
        before = move["evaluation_before"]["outcome_units"]
        after = move["evaluation_after"]["outcome_units"]
        loss = move["loss_units"]
        if transition == "lost":
            loss = max(loss, C.MATE_LOSS_FLOOR)
        decided = before <= C.DECIDED_LOW or before >= C.DECIDED_HIGH
        if decided and loss <= 40 and (after <= C.DECIDED_LOW or after >= C.DECIDED_HIGH):
            continue
        weight = .25 if decided else .5 if move.get("forced_tactical") else 1.0
        total += weight
        weighted += weight * (loss / 2000) ** 2
        included += 1
    return {"value": round(100 * math.exp(-4 * math.sqrt(weighted / total)), 1) if total else None,
            "included_moves": included, "weight": total, "accuracy_model_version": C.ACCURACY_VERSION,
            "experimental": True}
