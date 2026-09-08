import unittest
import chess
from backend.practice import config
from scripts.calibrate_bots import TAGGED_CORPUS


class BotCalibrationCorpusTests(unittest.TestCase):
    def test_tagged_corpus_is_large_and_valid(self):
        self.assertGreaterEqual(len(TAGGED_CORPUS), 60)
        self.assertGreaterEqual(len({fen for fen, _ in TAGGED_CORPUS}), 60)
        for fen, category in TAGGED_CORPUS:
            chess.Board(fen)
            self.assertTrue(category)

    def test_strength_controls_are_monotonic_and_crown_is_tightest(self):
        profiles = list(config.ROSTER)
        self.assertEqual([bot.estimated_strength for bot in profiles], list(range(600, 2401, 200)))
        self.assertEqual(sorted(bot.search_seconds for bot in profiles), [bot.search_seconds for bot in profiles])
        self.assertEqual(sorted(bot.search_depth for bot in profiles), [bot.search_depth for bot in profiles])
        self.assertEqual(profiles[-1].max_cp_loss, min(bot.max_cp_loss for bot in profiles))
        self.assertEqual(profiles[-1].mistake_frequency, 0)


if __name__ == "__main__":
    unittest.main()
