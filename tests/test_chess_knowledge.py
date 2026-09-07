import unittest
import chess

from backend.chess_knowledge import CoachContext, analyze_position
from backend.chess_knowledge.knowledge import detect_phase


class ChessKnowledgeTests(unittest.TestCase):
    def test_opening_phase_and_development_purpose(self):
        board = chess.Board()
        knowledge = analyze_position(board, chess.Move.from_uci("g1f3"))
        self.assertEqual(knowledge["phase"], "opening")
        self.assertIn("develop_piece", {item["type"] for item in knowledge["move_purpose"]})

    def test_check_and_capture_are_evidence_backed(self):
        board = chess.Board("6k1/5q2/8/8/8/8/6R1/6K1 w - - 0 1")
        move = chess.Move.from_uci("g2g7")
        self.assertIn(move, board.legal_moves)
        knowledge = analyze_position(board, move)
        self.assertIn("check", {item["type"] for item in knowledge["tactical_motifs"]})
        self.assertIn("fork", {item["type"] for item in knowledge["tactical_motifs"]})

    def test_strategic_and_activity_evidence_is_structured(self):
        knowledge = analyze_position(chess.Board())
        types = {item["type"] for item in knowledge["positional_features"]}
        self.assertIn("bishop_pair", types)
        self.assertTrue(knowledge["piece_activity"])

    def test_coach_context_issue_lifecycle_and_bounded_history(self):
        context = CoachContext(max_moves=6)
        board = chess.Board()
        bad = analyze_position(board, chess.Move.from_uci("d1h5")) if chess.Move.from_uci("d1h5") in board.legal_moves else analyze_position(board)
        context.update(ply=1, move="d1h5", classification="Mistake", knowledge=bad)
        context.update(ply=2, move="g1f3", classification="Good", knowledge=analyze_position(board, chess.Move.from_uci("g1f3")))
        for ply in range(3, 12):
            context.update(ply=ply, move="g1f3", classification="Good", knowledge={})
        state = context.to_dict()
        self.assertLessEqual(len(state["recent_moves"]), 6)
        self.assertIn("delayed_development", state["issue_counters"])

    def test_coach_context_repetition_and_correction(self):
        context = CoachContext()
        empty = {"king_safety": {}, "pawn_features": [], "coaching_topics": []}
        context.update(ply=1, move="a2a3", classification="Good", knowledge=empty)
        first = context.to_dict()["issue_states"]["delayed_development"]
        context.update(ply=2, move="h7h6", classification="Good", knowledge=empty)
        repeated = context.to_dict()["issue_states"]["delayed_development"]
        develop = analyze_position(chess.Board(), chess.Move.from_uci("g1f3"))
        context.update(ply=3, move="g1f3", classification="Good", knowledge=develop)
        resolved = context.to_dict()["issue_states"]["delayed_development"]
        self.assertEqual(first, "detected")
        self.assertEqual(repeated, "repeated")
        self.assertEqual(resolved, "resolved")

    def test_passed_and_doubled_pawn_features(self):
        board = chess.Board("4k3/8/8/8/8/P7/P7/4K3 w - - 0 1")
        types = {item["type"] for item in analyze_position(board)["pawn_features"]}
        self.assertIn("doubled_pawn", types)
        self.assertIn("passed_pawn", types)

    def test_endgame_phase_is_material_based(self):
        board = chess.Board("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")
        self.assertEqual(detect_phase(board), "endgame")

    def test_criticality_uses_existing_candidates_without_engine_calls(self):
        knowledge = analyze_position(chess.Board(), intelligence={"candidates": [
            {"move": "e2e4", "outcome_units": 1500},
            {"move": "d2d4", "outcome_units": 1300},
        ]})
        self.assertTrue(knowledge["criticality"]["is_critical"])
        self.assertEqual(knowledge["criticality"]["evidence"]["gap_units"], 200)

    def test_opening_metadata_requires_real_book_evidence(self):
        board = chess.Board()
        unknown = analyze_position(board)
        self.assertEqual(unknown["opening"]["book_status"], "unknown")
        known = analyze_position(board, book={"book_move": "e2e4", "book_source": "book.bin", "eco": "B00"})
        self.assertEqual(known["opening"]["book_status"], "verified")
        self.assertEqual(known["opening"]["eco"], "B00")


if __name__ == "__main__":
    unittest.main()
