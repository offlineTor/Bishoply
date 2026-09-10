import os
import tempfile
import unittest
from pathlib import Path

from backend.database import db
from backend.services.competitive import ensure_player, join, status


class CompetitiveIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_path, self.old_url = db.DB_PATH, db.DATABASE_URL
        self.temp = tempfile.TemporaryDirectory(); db.DB_PATH = Path(self.temp.name) / "competitive.db"; db.DATABASE_URL = ""
        await db.initialize_database()
        connection = await db.connect()
        await connection.execute("INSERT INTO users(discord_id,username,username_normalized,display_name) VALUES (NULL,'alice','alice','Alice')")
        await connection.execute("INSERT INTO users(discord_id,username,username_normalized,display_name) VALUES (NULL,'bob','bob','Bob')")
        await connection.commit(); await connection.close()

    async def asyncTearDown(self):
        db.DB_PATH, db.DATABASE_URL = self.old_path, self.old_url; self.temp.cleanup()

    async def test_web_players_share_generic_queue(self):
        alice = await ensure_player("web", "1", 1)
        bob = await ensure_player("web", "2", 2)
        self.assertNotEqual(alice, bob)
        self.assertEqual((await join(alice))["status"], "queued")
        result = await join(bob)
        self.assertEqual(result["status"], "matched")
        self.assertEqual((await status(alice))["status"], "matched")
