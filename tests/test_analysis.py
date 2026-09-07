"""Run: .venv/bin/python -m unittest discover -s tests -v (isolated SQLite only)."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine
import httpx
from fastapi import FastAPI

from backend.analysis import service
from backend.analysis import config as C
from backend.analysis.worker import run_review
from backend.api.analysis import router
from backend.database import db as database
from backend.services import game_service


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = database.DB_PATH
        database.DB_PATH = Path(self.temp.name) / "test.db"
        await database.initialize_database()
        db = await database.connect()
        await db.executescript(service.SCHEMA)
        await db.close()
        await database.get_or_create_user(101, "white", "White Player")
        await database.get_or_create_user(202, "black", "Black Player")
        self.game = (await game_service.create_casual_game(101))["game"]
        self.game_id = self.game["game_id"]
        app = FastAPI()
        app.include_router(router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        database.DB_PATH = self.old_path
        self.temp.cleanup()

    async def test_live_gate_and_game_flow(self):
        path = f"/api/games/{self.game_id}/analysis"
        for method in (self.client.get, self.client.post):
            self.assertEqual((await method(path)).status_code, 409)
        joined = await game_service.join_casual_game(self.game_id, 202)
        self.assertEqual(joined["game"]["status"], "active")
        self.assertIsNotNone(joined["game"]["white"]["chess_rating"])
        for method in (self.client.get, self.client.post):
            self.assertEqual((await method(path)).status_code, 409)
        illegal = await game_service.make_move(self.game_id, 101, "e2e5")
        self.assertFalse(illegal["ok"])
        for player, move in [(101,"f2f3"), (202,"e7e5"), (101,"g2g4"), (202,"d8h4")]:
            played = await game_service.make_move(self.game_id, player, move)
            self.assertTrue(played["ok"], played)
        finished = (await game_service.get_game(self.game_id))["game"]
        self.assertEqual(finished["status"], "black_win")
        self.assertEqual(len(finished["moves"]), 4)
        self.assertIn("competitive", finished)
        self.assertEqual((await self.client.post(path)).json()["status"], "queued")
        self.assertEqual((await self.client.post(path)).json()["status"], "queued")
        with patch.object(service, "run_review", return_value={"engine":"test", "moves":[]}) as run:
            self.assertTrue(await asyncio.to_thread(service.process_one))
            self.assertFalse(await asyncio.to_thread(service.process_one))
            self.assertEqual(run.call_count, 1)
        cached = (await self.client.get(path)).json()
        self.assertEqual(cached["status"], "complete")
        self.assertEqual((await self.client.post(path)).json(), cached)
        db = await database.connect()
        await db.execute("UPDATE games SET status='active' WHERE public_id=?", (self.game_id,))
        await db.commit()
        await db.close()
        self.assertEqual((await self.client.get(path)).status_code, 409)

    async def test_real_engine_queue_to_persisted_review(self):
        board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        starting_fen = board.fen()
        board.push_uci("f7g7")
        db = await database.connect()
        row = await (await db.execute("SELECT id, white_user_id FROM games WHERE public_id=?", (self.game_id,))).fetchone()
        await db.execute("UPDATE games SET starting_fen=?, current_fen=?, status='white_win' WHERE id=?", (starting_fen, board.fen(), row[0]))
        await db.execute("INSERT INTO game_moves(game_id,move_number,ply,user_id,color,uci,san,fen_after) VALUES (?,1,1,?,'white','f7g7','Qg7#',?)", (row[0], row[1], board.fen()))
        await db.commit()
        await db.close()
        queued = await service.get_review(self.game_id, True)
        self.assertEqual(queued["status"], "queued")
        await asyncio.to_thread(service.process_one, 'fast')
        partial = await service.get_review(self.game_id)
        self.assertEqual(partial['status'], 'queued')
        self.assertEqual(partial['result']['stage'], 'deep_queued')
        self.assertTrue(partial['result']['moves'][0]['preliminary'])
        self.assertFalse(partial['result']['moves'][0]['verification_occurred'])
        self.assertEqual(partial['result']['moves'][0]['evaluation_before']['depth'], C.FAST_DEPTH)
        await asyncio.to_thread(service.process_one, 'deep')
        review = await service.get_review(self.game_id)
        self.assertEqual(review["status"], "complete")
        self.assertEqual(review["result"]["moves"][0]["fen"], board.fen())
        self.assertGreaterEqual(review["result"]["moves"][0]["evaluation_before"]["depth"], C.NORMAL_DEPTH)
        self.assertEqual(await service.get_review(self.game_id, True), review)

    async def test_revisions_preserve_completed_results(self):
        await game_service.join_casual_game(self.game_id, 202)
        await game_service.resign_game(self.game_id, 101)
        await service.get_review(self.game_id, True)
        with patch.object(service, 'run_review', return_value={'engine':'first','moves':[]}):
            await asyncio.to_thread(service.process_one)
        first = await service.get_review(self.game_id)
        queued = await service.get_review(self.game_id, True, new_revision=True)
        self.assertEqual(queued['analysis_revision'], 2)
        while_pending = await service.get_review(self.game_id)
        self.assertEqual(while_pending['result'], first['result'])
        with patch.object(service, 'run_review', return_value={'engine':'second','moves':[]}):
            await asyncio.to_thread(service.process_one)
        second = await service.get_review(self.game_id)
        self.assertEqual(second['analysis_revision'], 2)
        db = await database.connect()
        rows = await (await db.execute('SELECT result FROM analysis_revisions WHERE subject_id=? ORDER BY revision',(self.game_id,))).fetchall()
        await db.close()
        self.assertEqual([json.loads(r[0])['engine'] for r in rows], ['first','second'])

    async def test_legacy_import_is_idempotent(self):
        db = await database.connect()
        game_id = (await (await db.execute('SELECT id FROM games WHERE public_id=?',(self.game_id,))).fetchone())[0]
        legacy = json.dumps({'engine':'Stockfish 19','moves':[],'settings':{'model':'bishoply-outcome-v1'}})
        await db.execute("INSERT INTO game_analysis(game_id,status,result) VALUES (?,'complete',?)",(game_id,legacy))
        await db.commit()
        await db.executescript(service.SCHEMA)
        await db.executescript(service.SCHEMA)
        rows = await (await db.execute('SELECT * FROM analysis_revisions WHERE subject_id=?',(self.game_id,))).fetchall()
        await db.close()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['result'],legacy)
        self.assertEqual(rows[0]['model_version'],'bishoply-outcome-v1')

    async def test_failure_and_retry(self):
        await game_service.join_casual_game(self.game_id, 202)
        resigned = await game_service.resign_game(self.game_id, 101)
        self.assertTrue(resigned["ok"])
        await service.get_review(self.game_id, True)
        with self.assertLogs(level="ERROR"), patch.object(service, "run_review", side_effect=RuntimeError("engine unavailable")):
            await asyncio.to_thread(service.process_one)
        self.assertEqual((await service.get_review(self.game_id))["status"], "failed")
        self.assertEqual((await service.get_review(self.game_id, True))["status"], "queued")


if __name__ == "__main__":
    unittest.main()
