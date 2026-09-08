import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch


class UnifiedAccountTests(unittest.TestCase):
    def test_discord_identity_backfill_and_repeat_login_are_single_account(self):
        async def scenario():
            from backend.database import db
            from backend import accounts
            old_path, old_url = db.DB_PATH, db.DATABASE_URL
            with tempfile.TemporaryDirectory() as directory, patch.object(db, "DB_PATH", os.path.join(directory, "accounts.db")), patch.object(db, "DATABASE_URL", ""), patch.dict(os.environ, {"SESSION_SECRET": "test-session-secret"}, clear=False):
                await db.initialize_database()
                connection = await db.connect()
                await connection.execute("INSERT INTO users(discord_id,username,display_name) VALUES (?,?,?)", (1546225609967935620, "discord-player", "Discord Player"))
                await connection.commit()
                await connection.close()
                first = await accounts.resolve("discord", "1546225609967935620", {"username": "discord-player"})
                second = await accounts.resolve("discord", "1546225609967935620", {"username": "discord-player"})
                self.assertEqual(first, second)
                connection = await db.connect()
                count = await (await connection.execute("SELECT COUNT(*) AS count FROM auth_identities WHERE provider=? AND subject=?", ("discord", "1546225609967935620"))).fetchone()
                self.assertEqual(count["count"], 1)
                await connection.close()
            db.DB_PATH, db.DATABASE_URL = old_path, old_url
        asyncio.run(scenario())

    def test_signed_state_rejects_provider_or_redirect_swap(self):
        from backend import accounts
        with patch.dict(os.environ, {"SESSION_SECRET": "test-session-secret"}, clear=False):
            state = accounts._state("google", "http://localhost:8000/api/auth/google/callback")
            with self.assertRaises(Exception):
                accounts._verify_state(state, "apple", "http://localhost:8000/api/auth/google/callback")


if __name__ == "__main__":
    unittest.main()
