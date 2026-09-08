"""Measure Practice bot selection on a deterministic Bishoply corpus.

This is an offline calibration tool; it never changes public strength labels or
the rated Duel path. Run with ``PYTHONPATH=. .venv/bin/python scripts/calibrate_bots.py``.
"""
import asyncio
import statistics
import time
import chess
from backend.practice import bots, config

CORPUS = (
    chess.STARTING_FEN,
    "2r3k1/pp3ppp/2p2n2/8/2B1P3/2N2N2/PP3PPP/2R3K1 w - - 0 18",
    "r1bq1rk1/ppp2ppp/2n5/3np3/3NP3/2N1B3/PPP2PPP/R2QKB1R w KQ - 0 8",
    "5rk1/ppp2ppp/2n5/3np3/3NP3/2N1B3/PPP2PPP/R2Q1RK1 w - - 0 12",
    "6k1/5ppp/8/2q5/3p4/5P2/5P1P/4R1K1 w - - 0 35",
    "6k1/5ppp/8/8/3P4/5P2/5P1P/4R1K1 w - - 0 35",
    "k7/P7/8/8/8/8/7p/7K w - - 0 60",
    "8/5pk1/3p2p1/1p1P4/1P2P3/5P2/5KP1/8 w - - 0 38",
    "r3k2r/ppp2ppp/2n5/3np3/3NP3/2N1B3/PPP2PPP/R2QK2R w KQkq - 0 10",
    "6k1/ppp2ppp/8/8/2B1P3/2N2N2/PP3PPP/6K1 w - - 0 20",
    "4r1k1/ppp2ppp/2n5/3np3/3NP3/2N1B3/PPP2PPP/R2Q1RK1 w - - 0 14",
    "3r2k1/ppp2ppp/8/8/3B1P2/2N2N2/PP3PPP/3R2K1 w - - 0 20",
    "2r3k1/ppp2ppp/8/3q4/3B1P2/2N2N2/PP3PPP/2R3K1 w - - 0 20",
    "8/8/4k3/8/3K4/8/4P3/8 w - - 0 50",
    "8/2p5/2p5/2P5/1P2K3/8/6k1/8 w - - 0 55",
    "4k3/8/8/3p4/3P4/8/4K3/8 w - - 0 50",
    "6k1/5ppp/8/8/3P4/5P2/5P1P/2R3K1 w - - 0 35",
    "2r3k1/ppp2ppp/2n5/3np3/3NP3/2N1B3/PPP2PPP/R2Q1RK1 b - - 0 14",
    "4r1k1/ppp2ppp/2n5/3np3/3NP3/2N1B3/PPP2PPP/R2Q1RK1 b - - 0 14",
    "8/5pk1/3p2p1/1p1P4/1P2P3/5P2/4P1K1/8 b - - 0 38",
    "6k1/ppp2ppp/8/8/2B1P3/2N2N2/PP3PPP/6K1 b - - 0 20",
    "k7/P7/8/8/8/8/7p/7K b - - 0 60",
    "2r3k1/ppp2ppp/8/3q4/3B1P2/2N2N2/PP3PPP/2R3K1 b - - 0 20",
    "7k/5Q2/7K/8/8/8/8/8 w - - 0 1",
    "4k3/8/8/8/8/3q4/4R3/4K3 w - - 0 1",
    "4k3/8/8/8/3B4/8/4R3/4K3 w - - 0 1",
    "4k3/8/8/8/3p4/8/4R3/4K3 w - - 0 1",
    "6k1/5ppp/8/8/3Q4/8/5PPP/6K1 w - - 0 1",
    "6k1/5ppp/8/8/3P4/5P2/5P1P/2R3K1 w - - 0 35",
    "8/8/8/8/3k4/8/3P4/3K4 w - - 0 50",
    "8/8/8/8/3k4/8/2PP4/3K4 w - - 0 50",
)

CATEGORIES = (
    "opening", "development", "quiet", "hanging", "fork", "knight_fork",
    "pin", "double_attack", "discovered_attack", "mate_in_one", "forcing_mate",
    "recapture", "king_safety", "castling", "passed_pawn", "pawn_race",
    "rook_endgame", "king_pawn_endgame", "winning", "losing", "tactical_defense",
    "quiet_best",
)
EXTRA_CATEGORIES = ("mate_in_one", "hanging", "pin", "fork", "winning", "passed_pawn", "king_pawn_endgame", "pawn_race")

# Mirroring doubles the corpus while preserving the tagged position class and
# exercises both colors without inventing an expected move.
TAGGED_CORPUS = []
for index, fen in enumerate(CORPUS):
    tag = EXTRA_CATEGORIES[index - 23] if index >= 23 else CATEGORIES[index % len(CATEGORIES)]
    board = chess.Board(fen)
    TAGGED_CORPUS.append((fen, tag))
    TAGGED_CORPUS.append((board.mirror().fen(), tag))


async def main():
    measurements = {bot.bot_id: [] for bot in config.ROSTER}
    failures = 0
    for index, (fen, category) in enumerate(TAGGED_CORPUS):
        board = chess.Board(fen)
        for bot in config.ROSTER:
            started = time.perf_counter()
            try:
                result = await bots.bot_move(board, bot.bot_id, f"calibration:{index}:{bot.bot_id}")
                elapsed = (time.perf_counter() - started) * 1000
                selected = result.get("selected", {})
                allowed = result.get("allowed_candidates", [])
                best = allowed[0] if allowed else {}
                loss = (best.get("cp") - selected.get("cp")) if best.get("cp") is not None and selected.get("cp") is not None else 0
                legal = chess.Move.from_uci(result["uci"]) in board.legal_moves
                child = board.copy(stack=False); child.push(chess.Move.from_uci(result["uci"]))
                mate_in_one = any(board.san(move).endswith("#") for move in board.legal_moves) and child.is_checkmate()
                hanging = category == "hanging" and board.is_capture(chess.Move.from_uci(result["uci"]))
                tactical = category in {"fork", "knight_fork", "pin", "double_attack", "discovered_attack", "tactical_defense", "forcing_mate"} and result.get("selected_rank", 99) <= 2 and (board.gives_check(chess.Move.from_uci(result["uci"])) or board.is_capture(chess.Move.from_uci(result["uci"])))
                material_blunder = loss >= 200
                measurements[bot.bot_id].append((result.get("selected_rank", 1), loss, elapsed, legal, tactical, mate_in_one, hanging, material_blunder, category))
            except Exception as exc:
                failures += 1
                print(f"FAIL {bot.bot_id} corpus={index} {type(exc).__name__}: {exc}")
    print("bot,positions,legal_pct,top1_pct,top2_pct,average_rank,average_cp_loss,tactical_pct,mate1_pct,hanging_punish_pct,material_blunder_pct,average_ms,failure_pct")
    for bot in config.ROSTER:
        rows = measurements[bot.bot_id]
        ranks = [row[0] for row in rows]
        legal = [row[3] for row in rows]
        tactical = [row[4] for row in rows if row[8] in {"fork", "knight_fork", "pin", "double_attack", "discovered_attack", "tactical_defense", "forcing_mate"}]
        mate = [row[5] for row in rows if row[8] == "mate_in_one"]
        hanging = [row[6] for row in rows if row[8] == "hanging"]
        blunders = [row[7] for row in rows]
        print(",".join(map(str, (bot.bot_id, len(rows),
            round(sum(legal) / len(legal) * 100, 1) if rows else 0,
            round(sum(rank == 1 for rank in ranks) / len(ranks) * 100, 1) if rows else 0,
            round(sum(rank <= 2 for rank in ranks) / len(ranks) * 100, 1) if rows else 0,
            round(statistics.mean(ranks), 2) if rows else 0,
            round(statistics.mean([row[1] for row in rows]), 1) if rows else 0,
            round(sum(tactical) / len(tactical) * 100, 1) if tactical else 0,
            round(sum(mate) / len(mate) * 100, 1) if mate else 0,
            round(sum(hanging) / len(hanging) * 100, 1) if hanging else 0,
            round(sum(blunders) / len(blunders) * 100, 1) if rows else 0,
            round(statistics.mean([row[2] for row in rows]), 1) if rows else 0,
            0 if rows else 100))))
    print(f"failures={failures} corpus_positions={len(TAGGED_CORPUS)}")
    await bots.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
