"""Evidence-backed chess semantics built on board state and existing engine data.

This module deliberately does not call Stockfish.  It is a shared fact layer for
Intelligence, Emma, review, and future personas.
"""
from __future__ import annotations

from typing import Any

import chess

KNOWLEDGE_SCHEMA_VERSION = "bishoply-chess-knowledge-v2"
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
HOME = {chess.B1, chess.C1, chess.F1, chess.G1,
        chess.B8, chess.C8, chess.F8, chess.G8}


def _name(square: int | None) -> str | None:
    return chess.square_name(square) if square is not None else None


def _side(color: chess.Color) -> str:
    return "white" if color else "black"


def _piece_value(piece: chess.Piece | None) -> int:
    return VALUES.get(piece.piece_type, 0) if piece else 0


def detect_phase(board: chess.Board) -> str:
    non_pawns = sum(1 for p in board.piece_map().values()
                    if p.piece_type not in (chess.PAWN, chess.KING))
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
    developed = sum(1 for square, p in board.piece_map().items()
                    if p.piece_type in (chess.KNIGHT, chess.BISHOP) and square not in HOME)
    if non_pawns <= 4 or (queens == 0 and non_pawns <= 6):
        return "endgame"
    if board.fullmove_number <= 10 and developed < 4 and queens == 2:
        return "opening"
    return "middlegame"


def material_context(board: chess.Board) -> dict[str, Any]:
    totals = {"white": 0, "black": 0}
    counts: dict[str, dict[str, int]] = {"white": {}, "black": {}}
    for piece in board.piece_map().values():
        side, name = _side(piece.color), chess.piece_name(piece.piece_type)
        totals[side] += _piece_value(piece)
        counts[side][name] = counts[side].get(name, 0) + 1
    return {"material": totals, "counts": counts,
            "difference": totals["white"] - totals["black"]}


def _pawn_files(board: chess.Board, color: chess.Color) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for square in board.pieces(chess.PAWN, color):
        result.setdefault(chess.square_file(square), []).append(square)
    return result


def _is_passed(board: chess.Board, square: int, color: chess.Color) -> bool:
    file, rank = chess.square_file(square), chess.square_rank(square)
    for enemy in board.pieces(chess.PAWN, not color):
        ef, er = chess.square_file(enemy), chess.square_rank(enemy)
        if abs(ef - file) <= 1 and ((color and er > rank) or (not color and er < rank)):
            return False
    return True


def pawn_features(board: chess.Board) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for color in (chess.WHITE, chess.BLACK):
        side = _side(color)
        files = _pawn_files(board, color)
        for file, squares in files.items():
            if len(squares) >= 2:
                features.append({"type": "tripled_pawn" if len(squares) >= 3 else "doubled_pawn",
                                 "side": side, "file": chess.FILE_NAMES[file],
                                 "squares": [_name(s) for s in sorted(squares)]})
        pawn_squares = list(board.pieces(chess.PAWN, color))
        for square in pawn_squares:
            file, rank = chess.square_file(square), chess.square_rank(square)
            adjacent = files.get(file - 1, []) + files.get(file + 1, [])
            if not adjacent:
                features.append({"type": "isolated_pawn", "side": side,
                                 "square": _name(square), "file": chess.FILE_NAMES[file]})
            if _is_passed(board, square, color):
                protected = any(board.piece_at(attacker) == chess.Piece(chess.PAWN, color)
                                for attacker in board.attackers(color, square))
                features.append({"type": "protected_passed_pawn" if protected else "passed_pawn",
                                 "side": side, "square": _name(square), "protected": protected})
        # A majority is only claimed when one side has more pawns in a wing.
        for wing, wing_files in (("queenside", (0, 1, 2, 3)), ("kingside", (4, 5, 6, 7))):
            own = sum(len(files.get(f, [])) for f in wing_files)
            other = sum(len(_pawn_files(board, not color).get(f, [])) for f in wing_files)
            if own > other:
                features.append({"type": "pawn_majority", "side": side, "wing": wing,
                                 "count": own - other})
    passers = [f for f in features if f["type"] in {"passed_pawn", "protected_passed_pawn"}]
    for passer in passers:
        square = chess.parse_square(passer["square"])
        color = chess.WHITE if passer["side"] == "white" else chess.BLACK
        rank = chess.square_rank(square)
        if (color and rank >= 4) or (not color and rank <= 3):
            passer["advanced"] = True
    return features


def king_safety(board: chess.Board) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for color in (chess.WHITE, chess.BLACK):
        king = board.king(color)
        shelter = []
        if king is not None:
            file, rank = chess.square_file(king), chess.square_rank(king)
            direction = 1 if color else -1
            shelter_rank = rank + direction
            if 0 <= shelter_rank < 8:
                shelter = [_name(chess.square(f, shelter_rank)) for f in range(max(0, file - 1), min(7, file + 1) + 1)
                           if board.piece_at(chess.square(f, shelter_rank)) == chess.Piece(chess.PAWN, color)]
        attackers = len(board.attackers(not color, king)) if king is not None else 0
        result[_side(color)] = {"king_square": _name(king), "attackers": attackers,
                                "in_check": bool(king is not None and board.is_attacked_by(not color, king)),
                                "castled": bool(board.has_kingside_castling_rights(color) is False and
                                                board.has_queenside_castling_rights(color) is False and
                                                king in ({chess.G1, chess.C1} if color else {chess.G8, chess.C8})),
                                "shelter_pawns": shelter,
                                "missing_shelter_files": max(0, 3 - len(shelter))}
    return result


def _line_between(a: int, b: int) -> list[int]:
    return list(chess.SquareSet(chess.between(a, b)))


def _slider_attacks(piece_type: int, delta_file: int, delta_rank: int) -> bool:
    diagonal = abs(delta_file) == abs(delta_rank)
    straight = delta_file == 0 or delta_rank == 0
    return (piece_type in (chess.BISHOP, chess.QUEEN) and diagonal) or (piece_type in (chess.ROOK, chess.QUEEN) and straight)


def _fork_or_double_attack(before: chess.Board, after: chess.Board, move: chess.Move) -> dict | None:
    piece = after.piece_at(move.to_square)
    if not piece:
        return None
    targets = []
    for square in after.attacks(move.to_square):
        victim = after.piece_at(square)
        if victim and victim.color != piece.color and victim.piece_type != chess.PAWN:
            targets.append(square)
    valuable = [s for s in targets if after.piece_at(s).piece_type == chess.KING or _piece_value(after.piece_at(s)) >= 3]
    if len(valuable) < 2:
        return None
    target_values = [_piece_value(after.piece_at(s)) for s in valuable]
    return {"type": "fork" if piece.piece_type == chess.KNIGHT or any(after.piece_at(s).piece_type == chess.KING for s in valuable) else "double_attack",
            "attacker": _name(move.to_square), "targets": [_name(s) for s in valuable],
            "target_values": target_values, "move": move.uci(), "forcing": after.is_check(), "confidence": "verified"}


def tactical_motifs(board: chess.Board, move: chess.Move | None) -> list[dict[str, Any]]:
    if move is None or move not in board.legal_moves:
        return []
    mover, piece = board.turn, board.piece_at(move.from_square)
    after = board.copy(stack=False)
    was_check = board.is_check()
    captured = board.piece_at(move.to_square)
    after.push(move)
    motifs: list[dict[str, Any]] = []
    if after.is_checkmate():
        motifs.append({"type": "checkmate", "move": move.uci(), "forcing": True, "confidence": "verified"})
    elif after.is_check():
        motifs.append({"type": "check", "move": move.uci(), "forcing": True, "confidence": "verified"})
    if after.is_check() and len(after.attackers(mover, after.king(not mover))) >= 2:
        motifs.append({"type": "double_check", "move": move.uci(), "forcing": True, "confidence": "verified"})
    if move.promotion:
        motifs.append({"type": "promotion_tactic", "move": move.uci(), "forcing": True, "confidence": "verified"})
    if captured:
        motifs.append({"type": "capture", "move": move.uci(), "captured": chess.piece_name(captured.piece_type),
                       "material_consequence": _piece_value(captured), "confidence": "verified"})
    fork = _fork_or_double_attack(board, after, move)
    if fork:
        motifs.append(fork)
    if piece and piece.piece_type != chess.KING and board.is_pinned(mover, move.from_square):
        king = board.king(mover)
        pin_type = "absolute_pin" if king is not None and move.from_square in board.attackers(not mover, king) else "relative_pin"
        motifs.append({"type": pin_type, "piece": chess.piece_name(piece.piece_type),
                       "square": _name(move.from_square), "move": move.uci(), "confidence": "verified"})
    # A discovered attack/check requires a line piece behind the moved piece.
    if piece and piece.piece_type != chess.KING and not was_check:
        enemy_king = after.king(not mover)
        for slider_square, slider in board.piece_map().items():
            if slider.color != mover or slider.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
                continue
            if enemy_king is None or move.from_square not in chess.SquareSet(chess.ray(slider_square, enemy_king)):
                continue
            before_attacks = slider_square in board.attackers(mover, enemy_king)
            after_attacks = slider_square in after.attackers(mover, enemy_king)
            if not before_attacks and after_attacks:
                motifs.append({"type": "discovered_check" if after.is_check() else "discovered_attack",
                               "attacker": _name(slider_square), "target": _name(enemy_king),
                               "move": move.uci(), "confidence": "verified", "forcing": after.is_check()})
                break
    return motifs


def strategic_features(board: chess.Board) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for color in (chess.WHITE, chess.BLACK):
        side = _side(color)
        occupied = [_name(s) for s in board.pieces(chess.PAWN, color) if s in CENTER]
        controlled = [_name(s) for s in CENTER if board.is_attacked_by(color, s)]
        if occupied: features.append({"type": "center_occupation", "side": side, "squares": occupied})
        if controlled: features.append({"type": "center_control", "side": side, "squares": controlled})
        bishops = list(board.pieces(chess.BISHOP, color))
        if len(bishops) >= 2: features.append({"type": "bishop_pair", "side": side, "squares": [_name(s) for s in bishops]})
        for file in range(8):
            own = len(_pawn_files(board, color).get(file, [])); enemy = len(_pawn_files(board, not color).get(file, []))
            if own == 0 and enemy == 0: features.append({"type": "open_file", "side": side, "file": chess.FILE_NAMES[file]})
            elif own == 0 and enemy > 0: features.append({"type": "semi_open_file", "side": side, "file": chess.FILE_NAMES[file]})
        for square in board.pieces(chess.ROOK, color):
            rank = chess.square_rank(square)
            if not _pawn_files(board, color).get(chess.square_file(square)):
                features.append({"type": "rook_on_open_file", "side": side, "square": _name(square)})
            if (color and rank == 6) or (not color and rank == 1):
                features.append({"type": "rook_on_seventh", "side": side, "square": _name(square)})
    return features


def piece_activity(board: chess.Board) -> list[dict[str, Any]]:
    result = []
    for square, piece in board.piece_map().items():
        if piece.piece_type != chess.KING:
            result.append({"side": _side(piece.color), "piece": chess.piece_name(piece.piece_type),
                           "square": _name(square), "legal_attack_count": len(board.attacks(square))})
    return result


def move_purpose(board: chess.Board, move: chess.Move | None, motifs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if move is None or move not in board.legal_moves:
        return []
    piece = board.piece_at(move.from_square); purposes = []
    if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP) and board.fullmove_number <= 12 and move.from_square in HOME:
        purposes.append({"type": "develop_piece", "evidence": move.uci()})
    if move.to_square in CENTER:
        purposes.extend(({"type": "occupy_center", "evidence": _name(move.to_square)}, {"type": "control_center", "evidence": _name(move.to_square)}))
    if board.is_castling(move): purposes.append({"type": "castle", "evidence": move.uci()})
    if board.gives_check(move): purposes.append({"type": "give_check", "evidence": move.uci()})
    if board.is_capture(move): purposes.append({"type": "win_material", "evidence": move.uci()})
    for motif in motifs:
        if motif["type"] in {"fork", "double_attack", "discovered_attack", "discovered_check"}:
            purposes.append({"type": "create_threat", "evidence": motif})
        if motif["type"] in {"absolute_pin", "relative_pin"}:
            purposes.append({"type": "create_threat", "evidence": motif})
    return purposes


def _criticality(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(candidates, key=lambda c: int(c.get("outcome_units", 0)), reverse=True)
    gaps = [int(ranked[i]["outcome_units"]) - int(ranked[i + 1]["outcome_units"]) for i in range(min(2, len(ranked) - 1))]
    first_gap = gaps[0] if gaps else 0
    if first_gap >= 300: level, reason = "only_move_like", "large_wdl_gap"
    elif first_gap >= 100: level, reason = "critical", "meaningful_wdl_gap"
    elif first_gap >= 40: level, reason = "important", "small_wdl_gap"
    else: level, reason = "routine", None
    return {"level": level, "is_critical": level in {"critical", "only_move_like"}, "reason": reason,
            "evidence": {"best": ranked[0].get("move") if ranked else None,
                         "second": ranked[1].get("move") if len(ranked) > 1 else None,
                         "third": ranked[2].get("move") if len(ranked) > 2 else None,
                         "wdl_gaps": gaps, "gap_units": first_gap}}


def analyze_position(board: chess.Board, move: chess.Move | None = None,
                     intelligence: dict | None = None, book: dict | None = None,
                     context: dict | None = None) -> dict[str, Any]:
    motifs = tactical_motifs(board, move)
    purposes = move_purpose(board, move, motifs)
    candidates = (intelligence or {}).get("candidates", [])
    threats = [{"type": m["type"], "severity": "high", "creating_move": m.get("move"), "evidence": m}
               for m in motifs if m["type"] in {"fork", "double_attack", "discovered_attack", "discovered_check", "checkmate", "promotion_tactic"}]
    opening = {"name": None, "variation": None, "eco": None, "confidence": 0,
               "book_status": "unknown", "last_known_book_ply": None, "first_deviation_ply": None}
    if book:
        opening.update({"name": book.get("opening_name"), "eco": book.get("eco"), "confidence": 1.0,
                        "book_status": "verified", "book_move": book.get("book_move"),
                        "book_source": book.get("book_source")})
    reasoning = {"what_happened": motifs[0]["type"] if motifs else None,
                 "why_it_matters": None, "what_to_notice": None, "next_plan": None,
                 "motifs": motifs, "strategic_topics": [p["type"] for p in purposes],
                 "evidence": motifs + purposes}
    if motifs:
        first = motifs[0]
        if first["type"] in {"fork", "double_attack"}:
            reasoning["why_it_matters"] = "attacks multiple valuable targets"
            reasoning["what_to_notice"] = "the forcing move limits the opponent's response"
        elif first["type"] in {"check", "checkmate", "discovered_check"}:
            reasoning["why_it_matters"] = "creates a forcing check"
            reasoning["what_to_notice"] = "the king must respond before other plans"
    return {"schema_version": KNOWLEDGE_SCHEMA_VERSION, "phase": detect_phase(board), "opening": opening,
            "tactical_motifs": motifs, "threats": threats, "positional_features": strategic_features(board),
            "pawn_features": pawn_features(board), "king_safety": king_safety(board),
            "piece_activity": piece_activity(board), "material_context": material_context(board),
            "move_purpose": purposes, "sacrifice_evidence": {"detected": False,
                "status": "evidence_only", "reason": "requires matched continuation and engine result"},
            "criticality": _criticality(candidates), "reasoning": reasoning,
            "coach_reasoning": reasoning,
            "coaching_topics": [p["type"] for p in purposes],
            "great_candidate": {"enabled": False, "evidence_ready": False},
            "brilliant_candidate": {"enabled": False, "evidence_ready": False},
            "supporting_evidence": [{"source": "board_state", "fen": board.fen()}],
            "coach_context": context}
