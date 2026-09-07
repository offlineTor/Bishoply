import tempfile
import unittest
from pathlib import Path

from backend.database import db
from backend.services.leaderboard import read


class LeaderboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "leaderboard.db"
        await db.initialize_database()
        for user_id in (1, 2, 3):
            await db.get_or_create_user(user_id, str(user_id), f"Player {user_id}")
        conn = await db.connect()
        await conn.execute("UPDATE skill_ratings SET rating=? WHERE user_id=? AND pool='standard'", (1800, 1))
        await conn.execute("UPDATE skill_ratings SET rating=? WHERE user_id=? AND pool='standard'", (1600, 2))
        await conn.execute("UPDATE progression SET sr=? WHERE user_id=?", (3000, 1))
        await conn.execute("UPDATE progression SET sr=? WHERE user_id=?", (2800, 2))
        await conn.commit(); await conn.close()

    async def asyncTearDown(self):
        db.DB_PATH = self.old
        self.temp.cleanup()

    async def test_separate_rating_and_sr_order_and_rank(self):
        ratings = await read("rating", current_user=3)
        self.assertEqual([row["chess_rating"] for row in ratings["entries"]], [1800, 1600, 1500])
        self.assertEqual(ratings["your_rank"]["rank"], 3)
        sr = await read("sr", current_user=2)
        self.assertEqual([row["sr"] for row in sr["entries"]], [3000, 2800, 2500])
        self.assertEqual(sr["your_rank"]["rank"], 2)

    async def test_pagination_and_no_private_fields(self):
        page = await read("rating", limit=1, offset=1)
        self.assertEqual(page["entries"][0]["rank"], 2)
        self.assertNotIn("discord_id", page["entries"][0])
        self.assertNotIn("integrity_status", page["entries"][0])


if __name__ == "__main__":
    unittest.main()
