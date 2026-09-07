import unittest
import chess
from backend.analysis.intelligence import CanonicalEvaluation, canonical_evaluation, player_perspective_units, opportunity_loss, move_accuracy, game_accuracy
from backend.analysis.concepts import extract, coach_for

def ev(units, cp=0, mate=None, perspective='white'):
    return {'outcome_units': units, 'cp': cp, 'mate': mate, 'wdl': [units//2, units-(units//2), 0], 'perspective': perspective}

class IntelligenceTests(unittest.TestCase):
    def test_canonical_evaluation_and_perspective(self):
        value = canonical_evaluation(ev(1600))
        self.assertIsInstance(value, CanonicalEvaluation)
        self.assertEqual(value.outcome_units, 1600)
        self.assertAlmostEqual(value.win_probability, .8)
        self.assertEqual(value.pawns, 0)
        self.assertEqual(player_perspective_units(ev(1600), 'white'), 1600)
        self.assertEqual(player_perspective_units(ev(1600), 'black'), 400)

    def test_common_root_loss_is_integer_and_forced_zero(self):
        self.assertEqual(opportunity_loss(ev(1600), ev(1590)), 10)
        self.assertEqual(opportunity_loss(ev(1600), ev(0), forced=True), 0)

    def test_move_accuracy_boundaries_and_mate_floor(self):
        self.assertEqual(move_accuracy(0), 100)
        self.assertLess(move_accuracy(1000), 20)
        self.assertEqual(move_accuracy(0, forced=True), None)
        self.assertEqual(move_accuracy(0, mate_transition='lost'), move_accuracy(360))

    def test_game_accuracy_does_not_dilute_with_forced_or_book(self):
        row = {'move_accuracy': 100, 'loss_units': 0, 'evaluation_before': {'outcome_units': 1000}}
        result = game_accuracy([row] + [{**row, 'forced_move': True}] * 20)
        self.assertEqual(result['value'], 100)
        self.assertEqual(result['included_moves'], 1)

    def test_concepts_have_evidence_and_Emma_is_conservative(self):
        board = chess.Board()
        concepts = extract(board, chess.Move.from_uci('e2e4'))
        self.assertTrue(any(c['topic'] == 'center_occupation' for c in concepts))
        coach = coach_for('Good', concepts)
        self.assertTrue(coach['should_comment'])
        self.assertTrue(all('evidence' in c for c in concepts))

if __name__ == '__main__': unittest.main()
