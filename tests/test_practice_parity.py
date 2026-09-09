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
            moved = await service.player_move(web_game["game_id"], web_game["access_key"], "e2e4", 0)
            replied = await service.bot_response(web_game["game_id"], web_game["access_key"], moved["ply"])
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

    async def test_active_game_cleanup_keeps_newest_only(self):
        from backend.practice import service
        from backend.practice import storage
        first = await service.create(None, "scout", "white", user_id=self.user["id"])
        second = await service.create(None, "tempo", "white", user_id=self.user["id"])
        connection = await self.db_module.connect()
        rows = await (await connection.execute("SELECT public_id,status,termination_reason FROM practice_games WHERE owner_user_id=? ORDER BY id", (self.user["id"],))).fetchall()
        await connection.close()
        active = [row for row in rows if row["status"] == "active"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["public_id"], second["game_id"])
        self.assertEqual(rows[0]["termination_reason"], "superseded")

    async def test_recovery_repairs_seven_legacy_active_games_and_allows_move(self):
        from backend.practice import service
        from backend.practice import storage
        from backend.api import practice as api
        from backend import accounts
        # Seed an old-style set of active rows directly to model the
        # production state observed before the integrity policy existed.
        seed = await service.create(1546225609967935620, "scout", "white")
        connection = await self.db_module.connect()
        source = await (await connection.execute(
            "SELECT * FROM practice_games WHERE public_id=?", (seed["game_id"],))).fetchone()
        for index in range(6):
            await connection.execute("""INSERT INTO practice_games
                (public_id,owner_discord_id,owner_user_id,access_hash,player_color,bot_id,
                 bot_strength,bot_personality,bot_config,starting_fen,current_fen,ply,revision,status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    f"practice_legacy_{index}", 1546225609967935620,
                    self.user["id"] if index else None, source["access_hash"],
                    source["player_color"], source["bot_id"], source["bot_strength"],
                    source["bot_personality"], source["bot_config"], source["starting_fen"],
                    source["current_fen"], 0, 0, "active"))
        # Make the recovered seed the newest valid row, as the production
        # cleanup policy requires deterministic newest-game selection.
        await connection.execute(
            "UPDATE practice_games SET created_at='2999-01-01 00:00:00' WHERE public_id=?",
            (seed["game_id"],))
        await connection.commit()
        await connection.close()

        # Startup is repeated on Render restarts; the cleanup and additive
        # schema path must remain idempotent.
        await storage.initialize()

        with patch.object(accounts, "session_user", new=AsyncMock(return_value=self.user["id"])):
            recovered = await api.active_game(SimpleNamespace(), None)
        self.assertTrue(recovered["active"])
        self.assertEqual(recovered["game"]["game_id"], seed["game_id"])

        with patch("backend.practice.service.bots.bot_move", new=AsyncMock(
                return_value={"uci": "e7e5", "selected": {}, "allowed_candidates": []})):
            moved = await service.player_move(
                recovered["game_id"], None, "e2e4", None,
                owner_user_id=self.user["id"])
            replied = await service.bot_response(
                recovered["game_id"], None, moved["ply"],
                owner_user_id=self.user["id"])
        self.assertEqual(replied["ply"], 2)
        self.assertEqual(len(replied["moves"]), 2)
        self.assertEqual(replied["turn"], "white")
        self.assertEqual(chess.Board(replied["fen"]).turn, chess.WHITE)

        connection = await self.db_module.connect()
        active_count = await (await connection.execute(
            "SELECT COUNT(*) FROM practice_games WHERE owner_user_id=? AND status='active'",
            (self.user["id"],))).fetchone()
        superseded = await (await connection.execute(
            "SELECT COUNT(*) FROM practice_games WHERE termination_reason='superseded'",
        )).fetchone()
        await connection.close()
        self.assertEqual(active_count[0], 1)
        self.assertGreaterEqual(superseded[0], 5)

    def test_move_request_normalizes_legacy_uci_field(self):
        from backend.api.practice import MoveRequest
        self.assertEqual(MoveRequest.model_validate({"uci": "e2e4", "expected_ply": 0}).move, "e2e4")
        with self.assertRaises(Exception):
            MoveRequest.model_validate({"expected_ply": 0})

    async def test_raw_discord_move_payloads_enter_route_without_fastapi_body_validation(self):
        from backend.api import practice as api
        from unittest.mock import AsyncMock
        class Request:
            headers = {"content-type": "application/json"}
            async def json(self): return self.payload
        for payload in ({"move": "e2e4", "expected_ply": 0}, {"uci": "e2e4"}):
            request = Request(); request.payload = payload
            with patch.object(api, "authenticated_owner", new=AsyncMock(return_value=(self.user["id"], 1546225609967935620))), patch.object(api.service, "player_move", new=AsyncMock(return_value={"ply": 1})) as moved:
                result = await api.player_move("practice_test", request, None, "Bearer token")
            self.assertEqual(result["ply"], 1)
            self.assertEqual(moved.await_args.args[2], "e2e4")


if __name__ == "__main__":
    unittest.main()
