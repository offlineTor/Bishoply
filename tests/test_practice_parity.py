import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import chess


class PracticeParityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from backend.database import db
        from backend.practice import storage
        self.db_module = db
        self.original_path, self.original_url = db.DB_PATH, db.DATABASE_URL
        self.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp.name) / "parity.db"
        db.DATABASE_URL = ""
        await db.initialize_database()
        await storage.initialize()
        from backend.analysis import service as analysis
        await analysis.initialize()
        for task in analysis._worker or []:
            task.cancel()
        if analysis._worker:
            await asyncio.gather(*analysis._worker, return_exceptions=True)
        analysis._worker = None
        await db.get_or_create_user(1546225609967935620, "discord-player", "Discord Player")
        connection = await db.connect()
        self.user = await (await connection.execute("SELECT id FROM users WHERE discord_id=?", (1546225609967935620,))).fetchone()
        await connection.close()

    async def asyncTearDown(self):
        self.db_module.DB_PATH, self.db_module.DATABASE_URL = self.original_path, self.original_url
        self.temp.cleanup()

    async def test_discord_and_web_creation_share_canonical_owner_and_engine_path(self):
        from backend.practice import service
        discord_game = await service.create(1546225609967935620, "scout", "white")
        web_game = await service.create(None, "scout", "white", user_id=self.user["id"])
        connection = await self.db_module.connect()
        rows = await (await connection.execute("SELECT owner_discord_id,owner_user_id FROM practice_games ORDER BY id")).fetchall()
        await connection.close()
        self.assertEqual(rows[0]["owner_user_id"], self.user["id"])
        self.assertEqual(rows[1]["owner_user_id"], self.user["id"])
        self.assertEqual(rows[0]["owner_discord_id"], 1546225609967935620)
        self.assertIsNone(rows[1]["owner_discord_id"])

        with patch("backend.practice.service.bots.bot_move", new=AsyncMock(return_value={"uci": "e7e5", "selected": {}, "allowed_candidates": []})):
            moved = await service.player_move(discord_game["game_id"], discord_game["access_key"], "e2e4", 0)
            replied = await service.bot_response(discord_game["game_id"], discord_game["access_key"], moved["ply"])
        self.assertEqual(len(replied["moves"]), 2)
        self.assertEqual(replied["moves"][1]["actor"], "bot")
        self.assertEqual(replied["turn"], "white")
        self.assertEqual(chess.Board(replied["fen"]).turn, chess.WHITE)

    async def test_practice_history_is_canonical_and_frontend_compatible(self):
        from backend.practice import service
        from backend.api import practice as api
        await service.create(None, "tempo", "black", user_id=self.user["id"])
        request = SimpleNamespace()
        with patch("backend.accounts.session_user", new=AsyncMock(return_value=self.user["id"])):
            result = await api.practice_history(request, None, 20, 0)
        self.assertEqual(result["games"][0]["game_id"].split("_")[0], "practice")
        self.assertEqual(result["games"][0]["user_color"], "black")
        self.assertEqual(result["games"][0]["opponent"]["display_name"], "Tempo")
        self.assertIn("move_count", result["games"][0])

    async def test_active_recovery_uses_canonical_owner(self):
        from backend.practice import service
        from backend.api import practice as api
        from backend import accounts
        game = await service.create(None, "scout", "white", user_id=self.user["id"])
        with patch.object(accounts, "session_user", new=AsyncMock(return_value=self.user["id"])):
            result = await api.active_game(SimpleNamespace(), None)
        self.assertTrue(result["active"])
        self.assertEqual(result["game_id"], game["game_id"])

    async def test_active_recovery_returns_empty_without_game(self):
        from backend.api import practice as api
        from backend import accounts
        with patch.object(accounts, "session_user", new=AsyncMock(return_value=self.user["id"])):
            result = await api.active_game(SimpleNamespace(), None)
        self.assertFalse(result["active"])


if __name__ == "__main__":
    unittest.main()
