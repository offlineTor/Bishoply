import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import chess


class PracticeMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_table_gets_owner_user_id_before_dependent_index(self):
        from backend.database import db
        from backend.practice import storage

        original_path, original_url = db.DB_PATH, db.DATABASE_URL
        with tempfile.TemporaryDirectory() as directory:
            db.DB_PATH = Path(directory) / "legacy.db"
            db.DATABASE_URL = ""
            try:
                await db.initialize_database()
                connection = await db.connect()
                # Reproduce the pre-Unified Accounts table: same schema, but
                # without owner_user_id and without its dependent index.
                legacy_schema = storage.SCHEMA.replace(
                    " owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,\n", ""
                )
                await connection.executescript(legacy_schema)
                await connection.execute(
                    "INSERT INTO users(discord_id,username,display_name) VALUES (?,?,?)",
                    (1546225609967935620, "legacy", "Legacy Player"),
                )
                await connection.execute(
                    """INSERT INTO practice_games(
                        public_id,owner_discord_id,access_hash,player_color,bot_id,
                        bot_strength,bot_personality,bot_config,starting_fen,current_fen,status
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    ("legacy_game", 1546225609967935620, "hash", "white", "scout",
                     600, "Forgiving", json.dumps({}), chess.STARTING_FEN,
                     chess.STARTING_FEN, "active"),
                )
                await connection.commit()
                await connection.close()

                await storage.initialize()
                connection = await db.connect()
                columns = await db.get_table_columns(connection, "practice_games")
                row = await (await connection.execute(
                    "SELECT owner_discord_id,owner_user_id FROM practice_games WHERE public_id=?",
                    ("legacy_game",),
                )).fetchone()
                indexes = await (await connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                    ("practice_history_user",),
                )).fetchone()
                self.assertIn("owner_user_id", columns)
                self.assertEqual(row["owner_discord_id"], 1546225609967935620)
                self.assertEqual(row["owner_user_id"], 1)
                self.assertIsNotNone(indexes)
                await connection.close()

                # Restart/idempotency: the additive migration and index must
                # succeed again without duplicate-column errors or data loss.
                await storage.initialize()
            finally:
                db.DB_PATH, db.DATABASE_URL = original_path, original_url


if __name__ == "__main__":
    unittest.main()
