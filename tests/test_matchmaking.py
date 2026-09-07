import asyncio
import tempfile
import unittest
from pathlib import Path

from backend.database import db
from backend.services import matchmaking


class MatchmakingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "match.db"
        await db.initialize_database()
        for user_id in (101, 202, 303):
            await db.get_or_create_user(user_id, f"u{user_id}", f"User {user_id}")
        await matchmaking.initialize()

    async def asyncTearDown(self):
        db.DB_PATH = self.old
        self.temp.cleanup()

    async def test_two_users_receive_same_game_and_opposite_colors(self):
        first = await matchmaking.join(101)
        self.assertEqual(first["status"], "queued")
        second = await matchmaking.join(202)
        self.assertEqual(second["status"], "matched")
        state_a = await matchmaking.status(101)
        state_b = await matchmaking.status(202)
        self.assertEqual(state_a["game_id"], state_b["game_id"])
        self.assertNotEqual(state_a["player_color"], state_b["player_color"])

    async def test_duplicate_queue_and_self_match_are_rejected(self):
        await matchmaking.join(101)
        with self.assertRaises(Exception):
            await matchmaking.join(101)

    async def test_cancel_only_cancels_queued_entry(self):
        await matchmaking.join(101)
        cancelled = await matchmaking.cancel(101)
        self.assertEqual(cancelled["status"], "idle")
        await matchmaking.join(101)
        await matchmaking.join(202)
        matched = await matchmaking.cancel(101)
        self.assertEqual(matched["status"], "matched")

    async def test_active_game_is_returned_instead_of_queueing(self):
        await matchmaking.join(101)
        await matchmaking.join(202)
        state = await matchmaking.join(101)
        self.assertEqual(state["status"], "active_game")
        self.assertTrue(state["game_id"])


if __name__ == "__main__":
    unittest.main()
