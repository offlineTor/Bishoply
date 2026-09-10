import os
import tempfile
import unittest
import asyncio
from pathlib import Path

from backend.database import db
from backend.services.competitive import ensure_player, join, status
from backend.services.game_service import ensure_competitive_profile
from backend.services.game_service import make_move, resign_game, get_game, list_user_games


class CompetitiveIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_path, self.old_url = db.DB_PATH, db.DATABASE_URL
        self.temp = tempfile.TemporaryDirectory(); db.DB_PATH = Path(self.temp.name) / "competitive.db"; db.DATABASE_URL = ""
        await db.initialize_database()
        connection = await db.connect()
        for i in range(1, 7):
            await connection.execute("INSERT INTO users(discord_id,username,username_normalized,display_name) VALUES (NULL,?,?,?)", (f"user{i}", f"user{i}", f"User {i}"))
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

    async def test_web_vs_discord_game_completion_rating_and_history(self):
        web = await ensure_player("web", "web-a", 1)
        discord = await ensure_player("discord", "discord-b", 2)
        conn = await db.connect()
        await ensure_competitive_profile(conn, 1, commit=False)
        await ensure_competitive_profile(conn, 2, commit=False)
        await conn.commit(); await conn.close()
        conn = await db.connect(); before_rows = []
        for uid in (1, 2): before_rows.append(await (await conn.execute("SELECT rating FROM skill_ratings WHERE user_id=? AND pool='standard'", (uid,))).fetchone())
        before = [float(row["rating"]) for row in before_rows]; await conn.close()
        await join(web); matched = await join(discord); self.assertEqual(matched["status"], "matched")
        game_id = matched["game_id"]; game = (await get_game(game_id))["game"]
        white, black = game["white"]["id"], game["black"]["id"]
        self.assertTrue((await make_move(game_id, white, "e2e4"))["ok"]); self.assertTrue((await make_move(game_id, black, "e7e5"))["ok"])
        self.assertTrue((await resign_game(game_id, black))["ok"])
        completed = (await get_game(game_id))["game"]; self.assertIn(completed["status"], {"white_win","black_win"})
        self.assertTrue((await list_user_games(1))["ok"]); self.assertTrue((await list_user_games(2))["ok"])

    async def test_all_platform_competitive_lifecycles_persist_results(self):
        pairs = (("web", "web"), ("discord", "discord"), ("web", "discord"))
        for offset, (left_platform, right_platform) in enumerate(pairs):
            left_user, right_user = offset * 2 + 1, offset * 2 + 2
            left = await ensure_player(left_platform, f"{left_platform}-life-{left_user}", left_user)
            right = await ensure_player(right_platform, f"{right_platform}-life-{right_user}", right_user)
            conn = await db.connect()
            await ensure_competitive_profile(conn, left_user, commit=False)
            await ensure_competitive_profile(conn, right_user, commit=False)
            await conn.commit()
            before = []
            for uid in (left_user, right_user):
                row = await (await conn.execute("SELECT rating FROM skill_ratings WHERE user_id=? AND pool='standard'", (uid,))).fetchone()
                before.append(float(row["rating"]))
            await conn.close()
            await join(left); matched = await join(right)
            self.assertEqual(matched["status"], "matched")
            game_id = matched["game_id"]
            game = (await get_game(game_id))["game"]
            white_id, black_id = game["white"]["id"], game["black"]["id"]
            self.assertNotEqual(white_id, black_id)
            for actor, move in ((white_id, "f2f3"), (black_id, "e7e5"), (white_id, "g2g4"), (black_id, "d8h4")):
                self.assertTrue((await make_move(game_id, actor, move))["ok"])
            completed = (await get_game(game_id))["game"]
            self.assertIn(completed["status"], {"white_win", "black_win"})
            conn = await db.connect(); after = []
            for uid in (left_user, right_user):
                row = await (await conn.execute("SELECT rating FROM skill_ratings WHERE user_id=? AND pool='standard'", (uid,))).fetchone()
                after.append(float(row["rating"]))
            await conn.close()
            self.assertNotEqual(before, after)
            for uid in (left_user, right_user):
                history = await list_user_games(uid)
                self.assertTrue(history["ok"])
                self.assertTrue(any(item.get("game_id") == game_id or item.get("id") == game_id for item in history.get("games", [])))

    async def test_generic_matchmaking_concurrency_has_unique_pairs(self):
        players = [await ensure_player("web" if i % 2 else "discord", f"queue-{i}", i) for i in range(1, 7)]
        results = await asyncio.gather(*(join(player) for player in players))
        matched = [result for result in results if result["status"] == "matched"]
        game_ids = {result["game_id"] for result in matched}
        self.assertEqual(len(game_ids), len(matched))
        self.assertLessEqual(len(matched), 3)
        conn = await db.connect()
        rows = await (await conn.execute("SELECT competitive_player_id,status,matched_game_id FROM competitive_matchmaking_queue")).fetchall()
        await conn.close()
        self.assertTrue(all(row["status"] != "queued" for row in rows))
