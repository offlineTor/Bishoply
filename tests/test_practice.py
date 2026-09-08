"""Isolated Practice regression/security tests; no production database/network writes."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import chess
import httpx
from fastapi import FastAPI
from backend.database import db as database
from backend.analysis import service as analysis
from backend.practice import bots, config, service, storage
from backend.practice.auth import discord_identity
from backend.api.practice import router as practice_router
from backend.api.analysis import router as review_router
from backend.services import game_service


class PracticeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original=database.DB_PATH
        database.DB_PATH=Path(self.temp.name)/'practice.db'
        await database.initialize_database()
        await storage.initialize()
        db=await database.connect(); await db.executescript(analysis.SCHEMA); await db.close()
        await database.get_or_create_user(101,'white','Human')
        await database.get_or_create_user(202,'black','Other')
        app=FastAPI(); app.include_router(practice_router); app.include_router(review_router)
        app.dependency_overrides[discord_identity]=lambda:101
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test')
        self.app=app

    async def asyncTearDown(self):
        await self.client.aclose()
        database.DB_PATH=self.original
        self.temp.cleanup()

    async def create(self,color='white',bot='scout'):
        response=await self.client.post('/api/practice/games',json={'discord_id':101,'bot_id':bot,'player_color':color})
        self.assertEqual(response.status_code,201,response.text)
        data=response.json()
        return data,{'X-Practice-Key':data['access_key']}

    async def competitive_snapshot(self):
        db=await database.connect()
        tables=await (await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN ('practice_games','practice_moves','analysis_revisions','game_analysis') ORDER BY name")).fetchall()
        result={}
        for row in tables:
            result[row[0]]=[tuple(r) for r in await (await db.execute('SELECT * FROM "'+row[0]+'" ORDER BY rowid')).fetchall()]
        await db.close()
        return result

    async def test_creation_moves_hints_and_resign_never_change_competitive_data(self):
        before=await self.competitive_snapshot()
        game,headers=await self.create()
        base=f"/api/practice/games/{game['game_id']}"
        self.assertEqual(game['mode'],'practice'); self.assertTrue(game['unrated'])
        rec={'uci':'e2e4','san':'e4','evaluation':{'cp':10}}
        with patch.object(bots,'recommendation',new=AsyncMock(return_value=rec)):
            for stage in (1,2,3):
                hint=await self.client.post(base+'/hint',headers=headers,json={'expected_ply':0,'stage':stage})
                self.assertEqual(hint.status_code,200,hint.text)
                self.assertEqual(hint.json()['hint_count'],stage)
                self.assertEqual('recommended_move' in hint.json(),stage==3)
                self.assertEqual('destination' in hint.json(),stage>=2)
        moved=await self.client.post(base+'/move',headers=headers,json={'expected_ply':0,'move':'e2e4'})
        self.assertEqual(moved.status_code,200,moved.text)
        self.assertEqual(moved.json()['analysis']['status'],'queued')
        self.assertTrue(moved.json()['moves'][0]['assisted'])
        with patch.object(bots,'bot_move',new=AsyncMock(return_value={'uci':'e7e5'})):
            replied=await self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':1})
            self.assertEqual(replied.status_code,200,replied.text)
        resigned=await self.client.post(base+'/resign',headers=headers)
        self.assertEqual(resigned.json()['status'],'black_win')
        review=await self.client.post(base+'/review',headers=headers)
        self.assertEqual(review.json()['status'],'queued')
        with patch.object(analysis,'run_review',return_value={'mode':'practice','moves':[]}):
            await asyncio.to_thread(analysis.process_one,'review')
        self.assertEqual((await self.client.get(base+'/review',headers=headers)).json()['status'],'complete')
        self.assertEqual(before,await self.competitive_snapshot())

    async def test_player_move_followed_by_real_bot_reply(self):
        game, headers = await self.create(color='white', bot='scout')
        base = f"/api/practice/games/{game['game_id']}"
        moved = await self.client.post(base + '/move', headers=headers,
                                       json={'expected_ply': 0, 'move': 'e2e4'})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertTrue(moved.json()['needs_bot_move'])
        replied = await self.client.post(base + '/bot-move', headers=headers,
                                         json={'expected_ply': 1})
        self.assertEqual(replied.status_code, 200, replied.text)
        state = replied.json()
        self.assertEqual(state['ply'], 2)
        self.assertEqual(state['turn'], 'white')
        self.assertEqual(len(state['moves']), 2)
        self.assertEqual(state['moves'][0]['actor'], 'player')
        self.assertEqual(state['moves'][1]['actor'], 'bot')
        board = chess.Board(state['fen'])
        self.assertEqual(board.turn, chess.WHITE)

    async def test_authentication_and_extra_fen_rejected(self):
        wrong=await self.client.post('/api/practice/games',json={'discord_id':202,'bot_id':'scout'})
        self.assertEqual(wrong.status_code,403)
        injected=await self.client.post('/api/practice/games',json={'discord_id':101,'bot_id':'scout','fen':chess.STARTING_FEN})
        self.assertEqual(injected.status_code,422)
        game,headers=await self.create()
        base=f"/api/practice/games/{game['game_id']}"
        self.assertEqual((await self.client.get(base,headers={'X-Practice-Key':'wrong'})).status_code,403)
        response=await self.client.get(base,headers=headers)
        self.assertNotIn('access_hash',response.json()); self.assertNotIn('access_key',response.json())
        self.assertEqual((await self.client.post(base+'/analysis/0',headers=headers)).status_code,404)
        self.assertEqual((await self.client.post(base+'/review',headers=headers)).status_code,409)
        self.app.dependency_overrides.clear()
        self.assertEqual((await self.client.post('/api/practice/games',json={'discord_id':101,'bot_id':'scout'})).status_code,422)

    async def test_discord_token_validation(self):
        self.app.dependency_overrides.clear()
        payload={'discord_id':101,'bot_id':'scout'}
        for status,body,expected in ((200,{'id':'101'},201),(401,{},401),(200,{},503)):
            fake=AsyncMock()
            fake.get.return_value=httpx.Response(status,json=body)
            context=MagicMock()
            context.__aenter__=AsyncMock(return_value=fake)
            context.__aexit__=AsyncMock(return_value=False)
            with patch('backend.practice.auth.httpx.AsyncClient',return_value=context):
                response=await self.client.post('/api/practice/games',json=payload,
                    headers={'Authorization':'Bearer test-token'})
            self.assertEqual(response.status_code,expected,response.text)

    async def test_feedback_queue_failure_rolls_back_move(self):
        from fastapi import HTTPException
        game,headers=await self.create()
        base=f"/api/practice/games/{game['game_id']}"
        with patch.object(analysis,'enqueue_feedback',new=AsyncMock(side_effect=HTTPException(429,'Queue full'))):
            response=await self.client.post(base+'/move',headers=headers,json={'expected_ply':0,'move':'e2e4'})
        self.assertEqual(response.status_code,429)
        state=(await self.client.get(base,headers=headers)).json()
        self.assertEqual(state['ply'],0)
        self.assertEqual(state['moves'],[])

    async def test_active_multiplayer_cannot_use_practice_engine(self):
        for mode in ('casual','ranked'):
            game=(await game_service.create_casual_game(101))['game']
            await game_service.join_casual_game(game['game_id'],202)
            db=await database.connect()
            await db.execute('UPDATE games SET mode=? WHERE public_id=?',(mode,game['game_id']))
            await db.commit(); await db.close()
            for method in (self.client.get,self.client.post):
                response=await method(f"/api/games/{game['game_id']}/analysis")
                self.assertEqual(response.status_code,409)
            base=f"/api/practice/games/{game['game_id']}"
            for suffix,payload in (('/hint',{'expected_ply':0,'stage':1}),('/bot-move',{'expected_ply':0}),('/analysis/1',None),('/review',None)):
                response=await self.client.post(base+suffix,headers={'X-Practice-Key':'any'},json=payload)
                self.assertEqual(response.status_code,404,(suffix,response.text))
            for suffix in ('/hint','/evaluation','/best-move'):
                self.assertEqual((await self.client.get(f"/api/games/{game['game_id']}"+suffix)).status_code,404)
            await game_service.resign_game(game['game_id'],101)
            self.assertEqual((await self.client.post(f"/api/games/{game['game_id']}/analysis")).json()['status'],'queued')

    async def test_black_player_bot_turn_stale_and_illegal_moves(self):
        game,headers=await self.create('black')
        base=f"/api/practice/games/{game['game_id']}"
        self.assertTrue(game['needs_bot_move'])
        self.assertEqual((await self.client.post(base+'/move',headers=headers,json={'expected_ply':0,'move':'e7e5'})).status_code,409)
        with patch.object(bots,'bot_move',new=AsyncMock(return_value={'uci':'e2e4'})):
            response=await self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':0})
            self.assertEqual(response.status_code,200,response.text)
        illegal=await self.client.post(base+'/move',headers=headers,json={'expected_ply':1,'move':'e7e4'})
        self.assertEqual(illegal.status_code,422)
        moved=await self.client.post(base+'/move',headers=headers,json={'expected_ply':1,'move':'e7e5'})
        self.assertEqual(moved.status_code,200,moved.text)
        self.assertEqual((await self.client.post(base+'/move',headers=headers,json={'expected_ply':1,'move':'e7e5'})).status_code,409)
        self.assertEqual(moved.json()['moves'][0]['color'],'white')
        self.assertEqual(moved.json()['moves'][1]['color'],'black')

    async def test_bot_failure_releases_claim_without_move(self):
        game,headers=await self.create('black')
        base=f"/api/practice/games/{game['game_id']}"
        for error in (asyncio.TimeoutError(),RuntimeError('engine failed')):
            with patch.object(bots,'bot_move',new=AsyncMock(side_effect=error)):
                result=await self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':0})
                self.assertEqual(result.status_code,503,result.text)
            state=(await self.client.get(base,headers=headers)).json()
            self.assertEqual(state['ply'],0); self.assertFalse(state['busy']); self.assertTrue(state['bot_error'])
        with patch.object(bots,'bot_move',new=AsyncMock(return_value={'uci':'e2e4'})):
            self.assertEqual((await self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':0})).status_code,200)

    async def test_duplicate_bot_requests_and_resign_race(self):
        game,headers=await self.create('black')
        base=f"/api/practice/games/{game['game_id']}"
        started=asyncio.Event(); release=asyncio.Event()
        async def delayed(*args):
            started.set(); await release.wait(); return {'uci':'e2e4'}
        with patch.object(bots,'bot_move',new=delayed):
            task=asyncio.create_task(self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':0}))
            await started.wait()
            duplicate=await self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':0})
            self.assertEqual(duplicate.status_code,409)
            self.assertEqual((await self.client.post(base+'/resign',headers=headers)).status_code,200)
            release.set()
            result=await task
            self.assertEqual(result.status_code,409)
        self.assertEqual((await self.client.get(base,headers=headers)).json()['ply'],0)

    async def test_undo_player_and_bot_turn_restores_fen_and_history(self):
        game,headers=await self.create()
        base=f"/api/practice/games/{game['game_id']}"
        starting=game['fen']
        moved=await self.client.post(base+'/move',headers=headers,json={'expected_ply':0,'move':'e2e4'})
        self.assertEqual(moved.status_code,200)
        with patch.object(bots,'bot_move',new=AsyncMock(return_value={'uci':'e7e5'})):
            replied=await self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':1})
        self.assertEqual(replied.status_code,200)
        undone=await self.client.post(base+'/undo',headers=headers)
        self.assertEqual(undone.status_code,200,undone.text)
        self.assertEqual(undone.json()['removed_plies'],2)
        self.assertEqual(undone.json()['ply'],0)
        self.assertEqual(undone.json()['fen'],starting)
        self.assertEqual(undone.json()['turn'],'white')
        self.assertEqual(undone.json()['moves'],[])

    async def test_undo_player_only_and_completed_rejection(self):
        game,headers=await self.create()
        base=f"/api/practice/games/{game['game_id']}"
        await self.client.post(base+'/move',headers=headers,json={'expected_ply':0,'move':'e2e4'})
        undone=await self.client.post(base+'/undo',headers=headers)
        self.assertEqual(undone.status_code,200)
        self.assertEqual(undone.json()['removed_plies'],1)
        self.assertEqual(undone.json()['ply'],0)
        self.assertEqual((await self.client.post(base+'/undo',headers=headers)).status_code,409)
        await self.client.post(base+'/resign',headers=headers)
        self.assertEqual((await self.client.post(base+'/undo',headers=headers)).status_code,409)

    async def test_undo_invalidates_inflight_bot_response(self):
        game,headers=await self.create()
        base=f"/api/practice/games/{game['game_id']}"
        moved=await self.client.post(base+'/move',headers=headers,json={'expected_ply':0,'move':'e2e4'})
        self.assertEqual(moved.status_code,200)
        started=asyncio.Event(); release=asyncio.Event()
        async def delayed(*args):
            started.set(); await release.wait(); return {'uci':'e7e5'}
        with patch.object(bots,'bot_move',new=delayed):
            task=asyncio.create_task(self.client.post(base+'/bot-move',headers=headers,json={'expected_ply':1}))
            await started.wait()
            undone=await self.client.post(base+'/undo',headers=headers)
            self.assertEqual(undone.status_code,200,undone.text)
            self.assertEqual(undone.json()['ply'],0)
            release.set()
            stale=await task
        self.assertEqual(stale.status_code,409)
        final=await self.client.get(base,headers=headers)
        self.assertEqual(final.json()['ply'],0)
        self.assertEqual(final.json()['revision'],1)

    async def test_real_live_feedback_and_practice_review(self):
        game,headers=await self.create()
        base=f"/api/practice/games/{game['game_id']}"
        # Small legal position only in isolated DB, never accepted as HTTP input.
        board=chess.Board('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1')
        db=await database.connect()
        await db.execute('UPDATE practice_games SET starting_fen=?,current_fen=? WHERE public_id=?',(board.fen(),board.fen(),game['game_id']))
        await db.commit(); await db.close()
        moved=await self.client.post(base+'/move',headers=headers,json={'expected_ply':0,'move':'f7e7'})
        self.assertEqual(moved.status_code,200,moved.text)
        self.assertEqual(moved.json()['status'],'active')
        self.assertEqual((await self.client.get(base+'/analysis/1',headers=headers)).json()['status'],'queued')
        await asyncio.to_thread(analysis.process_one,'feedback')
        feedback=(await self.client.get(base+'/analysis/1',headers=headers)).json()
        self.assertEqual(feedback['status'],'complete',feedback)
        self.assertIn(feedback['result']['classification'],('Best','Excellent','Good','Inaccuracy','Mistake','Blunder','Miss','Book','Forced'))
        self.assertIn('verification_occurred',feedback['result'])
        self.assertEqual(feedback['result']['evaluation_before']['root_fen'],board.fen())
        await self.client.post(base+'/resign',headers=headers)
        await self.client.post(base+'/review',headers=headers)
        await asyncio.to_thread(analysis.process_one,'review')
        review=(await self.client.get(base+'/review',headers=headers)).json()
        self.assertEqual(review['status'],'complete',review)
        self.assertEqual(review['result']['mode'],'practice')
        self.assertEqual(review['result']['moves'][0]['classifier_version'],feedback['result']['classifier_version'])


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_profiles_have_ordered_strength_controls(self):
        profiles = list(config.ROSTER)
        self.assertEqual([p.estimated_strength for p in profiles], list(range(600, 2401, 200)))
        self.assertEqual(sorted(p.search_seconds for p in profiles), [p.search_seconds for p in profiles])
        self.assertEqual(sorted(p.search_depth for p in profiles), [p.search_depth for p in profiles])
        self.assertEqual(sorted((p.max_outcome_loss for p in profiles), reverse=True),
                         [p.max_outcome_loss for p in profiles])
        self.assertEqual(profiles[-1].mistake_frequency, 0)
        self.assertEqual(profiles[-1].selection_temperature, .35)

    async def test_all_configs_and_real_legal_moves_both_colors(self):
        self.assertEqual([b.estimated_strength for b in config.ROSTER],list(range(600,2401,200)))
        for bot in config.ROSTER:
            self.assertEqual(bot.public()['strength_label'],'Estimated Bot Strength')
            for black in (False,True):
                board=chess.Board()
                if black: board.push_uci('e2e4')
                result=await bots.bot_move(board,bot.bot_id,f'test:{black}')
                self.assertIn(chess.Move.from_uci(result['uci']),board.legal_moves)
                if bot.bot_id=='scout':
                    self.assertTrue(result['strength_control']['outside_supported_range'])
                if bot.bot_id=='crown':
                    self.assertFalse(result['strength_control']['options']['UCI_LimitStrength'])

    async def test_actual_timeout_cleans_engine(self):
        from contextlib import asynccontextmanager
        closed=[]
        @asynccontextmanager
        async def tracked():
            try: yield object()
            finally: closed.append(True)
        async def hang(engine): await asyncio.sleep(1)
        with patch.object(bots,'session',tracked),patch.object(config,'JOB_TIMEOUT',.03):
            with self.assertRaises(asyncio.TimeoutError):
                await bots.bounded(hang)
        self.assertEqual(closed,[True])

    async def test_personality_and_safety_band(self):
        board=chess.Board()
        development=bots.style_score(board,chess.Move.from_uci('g1f3'),'development')
        flank=bots.style_score(board,chess.Move.from_uci('a2a3'),'development')
        self.assertGreater(development,flank)
        candidates=[{'move':'e2e4','cp':50,'mate':None,'outcome_units':1050},
                    {'move':'d2d4','cp':20,'mate':None,'outcome_units':1020},
                    {'move':'a2a3','cp':-1000,'mate':None,'outcome_units':0}]
        seen=set()
        for seed in range(30):
            result,allowed=bots.choose_candidate(board,config.BOTS['scout'],candidates,'e2e4',str(seed))
            seen.add(result['move'])
            self.assertNotIn('a2a3',[c['move'] for c in allowed])
        self.assertEqual(seen,{'e2e4','d2d4'})

    async def test_real_staged_hint_engine_and_identity_rejection(self):
        rec=await bots.recommendation(chess.Board())
        self.assertIn(chess.Move.from_uci(rec['uci']),chess.Board().legal_moves)
        self.assertNotIn('recommended_move',service.projected_hint(rec,1))
        self.assertNotIn('evaluation',service.projected_hint(rec,1))
        self.assertIn('recommended_move',service.projected_hint(rec,3))
