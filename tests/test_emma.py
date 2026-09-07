import unittest
import json
import sqlite3

from backend.chess_knowledge.emma import compose_emma, game_summary
from backend.analysis.service import _load_practice_context, _save_practice_context
from backend.chess_knowledge import CoachContext


class EmmaTests(unittest.TestCase):
    def test_best_development_is_evidence_based(self):
        result = compose_emma(classification="Best", game_id="g", ply=4,
                              knowledge={"phase": "opening", "move_purpose": [{"type": "develop_piece"}],
                                         "tactical_motifs": []})
        self.assertTrue(result["should_comment"])
        self.assertTrue(any(word in result["message"] for word in ("piece", "army", "center")))

    def test_mistake_material_loss_is_high_priority(self):
        result = compose_emma(classification="Mistake", knowledge={"move_purpose": [{"type": "win_material"}]})
        self.assertTrue(result["should_speak"])
        self.assertIn("material", result["message"])

    def test_repeated_and_resolved_issue_continuity(self):
        repeated = compose_emma(classification="Good", context={"issue_states": {"delayed_development": "repeated"}}, knowledge={})
        resolved = compose_emma(classification="Good", context={"issue_states": {"delayed_development": "resolved"}}, knowledge={})
        self.assertEqual(repeated["issue_state"], "repeated")
        self.assertIn("again", repeated["message"])
        self.assertEqual(resolved["issue_state"], "resolved")
        self.assertIn("Better", resolved["message"])

    def test_good_without_evidence_is_silent(self):
        result = compose_emma(classification="Good", knowledge={})
        self.assertFalse(result["should_comment"])
        self.assertIsNone(result["message"])

    def test_variation_is_deterministic(self):
        kwargs = {"classification": "Best", "game_id": "g", "ply": 7,
                  "knowledge": {"phase": "opening", "move_purpose": [{"type": "develop_piece"}]}}
        self.assertEqual(compose_emma(**kwargs), compose_emma(**kwargs))

    def test_summary_uses_context_evidence(self):
        summary = game_summary(context={"issue_counters": {"hanging_piece_errors": 3}}, phase="middlegame")
        self.assertTrue(summary["should_comment"])
        self.assertIn("hanging piece", summary["message"])

    def test_context_persists_and_stale_or_duplicate_writes_are_rejected(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE practice_coach_context (game_id INTEGER PRIMARY KEY,last_ply INTEGER,revision INTEGER,context_json TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        context = CoachContext()
        context.update(ply=1, move="a2a3", classification="Good", knowledge={})
        self.assertTrue(_save_practice_context(db, 7, 1, 1, context))
        self.assertFalse(_save_practice_context(db, 7, 1, 1, context))
        self.assertFalse(_save_practice_context(db, 7, 2, 0, context))
        restored, last_ply, revision = _load_practice_context(db, 7)
        self.assertEqual((last_ply, revision), (1, 1))
        self.assertEqual(restored.to_dict()["recent_moves"][0]["ply"], 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
