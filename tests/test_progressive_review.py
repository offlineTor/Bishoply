"""Progressive publication, authority and score-packet regression tests."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import chess
from backend.analysis import service, worker
from backend.analysis.engine import Engine
from backend.database import db as database
from backend.services import game_service


class ProgressiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old=database.DB_PATH
        database.DB_PATH=Path(self.temp.name)/'review.db'
        await database.initialize_database()
        db=await database.connect(); await db.executescript(service.SCHEMA); await db.close()
        await database.get_or_create_user(101,'w','White')
        await database.get_or_create_user(202,'b','Black')
        self.game=(await game_service.create_casual_game(101))['game']
        self.id=self.game['game_id']
        await game_service.join_casual_game(self.id,202)
        await game_service.make_move(self.id,101,'e2e4')
        await game_service.resign_game(self.id,202)

    async def asyncTearDown(self):
        database.DB_PATH=self.old; self.temp.cleanup()

    async def test_terminal_board_reasons_and_repetition_history(self):
        fixtures=[('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1','f7g7','checkmate'),
                  ('7k/4Q3/6K1/8/8/8/8/8 w - - 0 1','e7f7','stalemate'),
                  ('7k/8/8/8/8/2n5/1B6/K7 w - - 0 1','b2c3','insufficient_material')]
        for fen,move,reason in fixtures:
            game=(await game_service.create_casual_game(101))['game']
            await game_service.join_casual_game(game['game_id'],202)
            db=await database.connect()
            await db.execute('UPDATE games SET starting_fen=?,current_fen=? WHERE public_id=?',(fen,fen,game['game_id']))
            await db.commit(); await db.close()
            result=await game_service.make_move(game['game_id'],101,move)
            self.assertTrue(result['ok'],result)
            self.assertEqual(result['game']['termination_reason'],reason)
        game=(await game_service.create_casual_game(101))['game']
        await game_service.join_casual_game(game['game_id'],202)
        for _ in range(4):
            for player,move in [(101,'g1f3'),(202,'g8f6'),(101,'f3g1'),(202,'f6g8')]:
                result=await game_service.make_move(game['game_id'],player,move)
                self.assertTrue(result['ok'],result)
        self.assertEqual(result['game']['termination_reason'],'fivefold_repetition')

    async def test_partial_persisted_then_superseded_cached(self):
        await service.get_review(self.id,True)
        observed=[]
        loop=asyncio.get_running_loop()
        def fake(game,moves,progress,publish):
            for stage,label,preliminary in [('fast_analysis','Good',True),('deep_analysis','Best',False)]:
                value={'stage':stage,'analyzed_plies':1,'total_plies':1,'percentage':100,
                       'moves':[{'ply':1,'classification':label,'preliminary':preliminary}]}
                progress(1); publish(value)
                observed.append(asyncio.run_coroutine_threadsafe(service.get_review(self.id),loop).result())
            return {**value,'stage':'complete'}
        with patch.object(service,'run_review',side_effect=fake) as run:
            await asyncio.to_thread(service.process_one)
            cached=await service.get_review(self.id,True)
            self.assertFalse(await asyncio.to_thread(service.process_one))
            self.assertEqual(run.call_count,1)
        self.assertEqual([r['status'] for r in observed],['fast_analysis','deep_analysis'])
        self.assertEqual(observed[0]['result']['moves'][0]['classification'],'Good')
        self.assertEqual(cached['status'],'complete')
        self.assertEqual(cached['result']['moves'][0]['classification'],'Best')
        db=await database.connect()
        await db.execute("UPDATE games SET status='active' WHERE public_id=?",(self.id,))
        await db.commit(); await db.close()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException): await service.get_review(self.id)

    async def test_fast_and_deep_lanes_reuse_revision(self):
        await service.get_review(self.id,True)
        def fake(game,moves,progress,publish,tiers,initial_result=None):
            fast=tiers==(True,)
            if not fast: self.assertEqual(initial_result['stage'],'deep_queued')
            return {'stage':'deep_queued' if fast else 'complete','moves':[], 'total_plies':1}
        with patch.object(service,'run_review',side_effect=fake) as run:
            self.assertFalse(await asyncio.to_thread(service.process_one,'deep'))
            self.assertTrue(await asyncio.to_thread(service.process_one,'fast'))
            fast=await service.get_review(self.id)
            self.assertEqual(fast['result']['stage'],'deep_queued')
            self.assertFalse(await asyncio.to_thread(service.process_one,'fast'))
            self.assertTrue(await asyncio.to_thread(service.process_one,'deep'))
            final=await service.get_review(self.id)
            self.assertEqual(final['analysis_revision'],fast['analysis_revision'])
            self.assertEqual(final['status'],'complete')
            self.assertEqual(run.call_count,2)

    async def test_failed_deep_keeps_fast_result(self):
        await service.get_review(self.id,True)
        def fake(game,moves,progress,publish):
            publish({'stage':'deep_analysis','moves':[{'ply':1,'classification':'Good','preliminary':True}]})
            raise RuntimeError('engine failed')
        with patch.object(service,'run_review',side_effect=fake),self.assertLogs(level='ERROR'):
            await asyncio.to_thread(service.process_one)
        result=await service.get_review(self.id)
        self.assertEqual(result['status'],'failed')
        self.assertTrue(result['result']['moves'][0]['preliminary'])

    async def test_latest_score_packet_drops_stale_bound_only(self):
        packets=[{'score':'old','lowerbound':True,'depth':10,'multipv':1},
                 {'score':'exact','depth':12,'multipv':1}, {'nodes':123}]
        class Analysis:
            def __aiter__(self):
                async def iterator():
                    for packet in packets: yield packet
                return iterator()
            async def wait(self): pass
            def stop(self): pass
        class Protocol:
            loop=asyncio.get_running_loop()
            async def analysis(self,*args,**kwargs): return Analysis()
        engine=Engine(); engine.engine=SimpleNamespace(protocol=Protocol())
        latest=await asyncio.to_thread(engine.raw_search,chess.Board(),12,1,None)
        self.assertEqual(latest,[{'score':'exact','depth':12,'multipv':1}])
        packets.append({'score':'bound','upperbound':True,'depth':12,'multipv':1})
        latest=await asyncio.to_thread(engine.raw_search,chess.Board(),12,1,None)
        self.assertTrue(latest[0]['upperbound'])


class PipelineTests(unittest.TestCase):
    def test_fast_all_plies_before_deep_and_failure_does_not_block_rest(self):
        board=chess.Board(); rows=[]
        for uci in ('e2e4','e7e5'):
            san=board.san(chess.Move.from_uci(uci));board.push_uci(uci)
            rows.append({'uci':uci,'san':san,'fen_after':board.fen()})
        calls=[]; updates=[]
        class FakeEngine:
            provenance={'engine':{'name':'test'},'settings':{}}
            def __enter__(self): return self
            def __exit__(self,*args): pass
        def analyze(engine,board,move,**options):
            calls.append((move.uci(),options['preliminary']))
            if not options['preliminary'] and move.uci()=='e2e4': raise RuntimeError('verification incomplete')
            return {'color':'white' if board.turn else 'black','classification':'Good' if options['preliminary'] else 'Best',
                    'preliminary':options['preliminary'],'authoritative':not options['preliminary']}
        with patch.object(worker,'Engine',FakeEngine),patch.object(worker,'analyze_move',side_effect=analyze):
            result=worker.run_review({'starting_fen':chess.STARTING_FEN,'current_fen':board.fen()},rows,
                                     publish=lambda data:updates.append(copy.deepcopy(data)))
        self.assertEqual(calls,[('e2e4',True),('e7e5',True),('e2e4',False),('e7e5',False)])
        self.assertEqual(result['stage'],'failed')
        self.assertTrue(result['moves'][0]['preliminary'])
        self.assertFalse(result['moves'][1]['preliminary'])
        self.assertIsNone(result['white_accuracy'])
        self.assertEqual(updates[1]['analyzed_plies'],1)
