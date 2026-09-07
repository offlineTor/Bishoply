"""Short-lived asynchronous UCI jobs; timeout/cancellation closes the engine.
Quick candidate assessment is for bot behavior, NEVER the review classifier.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import math
import os
import random
import shutil
import chess
import chess.engine
from backend.analysis.config import EXPECTED_ENGINE, PIECE_VALUES
from backend.analysis.engine import outcome
from . import config as C

_slots = asyncio.Semaphore(C.MAX_ENGINE_JOBS)


@asynccontextmanager
async def session():
    path = os.getenv('STOCKFISH_PATH') or shutil.which('stockfish')
    if not path:
        raise RuntimeError('Stockfish unavailable')
    transport, engine = await chess.engine.popen_uci(path)
    try:
        if engine.id.get('name') != os.getenv('BISHOPLY_STOCKFISH_VERSION', EXPECTED_ENGINE):
            raise RuntimeError('Unexpected Stockfish version')
        await engine.configure({'Threads':1,'Hash':32,'UCI_ShowWDL':True,'UCI_LimitStrength':False,'Skill Level':20})
        yield engine
    finally:
        # Give normal jobs a clean UCI exit; force-close stalled/cancelled engines.
        try:
            await asyncio.wait_for(engine.quit(), timeout=.25)
        except (asyncio.TimeoutError, chess.engine.EngineError, BrokenPipeError):
            pass
        finally:
            transport.close()
            try:
                await asyncio.wait_for(asyncio.shield(engine.returncode),timeout=.25)
            except asyncio.TimeoutError:
                pass


async def bounded(operation):
    async def limited():
        async with _slots:
            async with session() as engine:
                return await operation(engine)
    return await asyncio.wait_for(limited(), timeout=C.JOB_TIMEOUT)


def strength_settings(bot, engine, board):
    remaining=sum(PIECE_VALUES[p.piece_type] for p in board.piece_map().values())
    endgame_factor=min(1.0,remaining/6000)
    requested=bot.estimated_strength
    if bot.bot_id=='endgame':
        requested+=round(300*(1-endgame_factor))
    supports='UCI_Elo' in engine.options and 'UCI_LimitStrength' in engine.options
    if bot.bot_id=='crown':
        return {'options':{'UCI_LimitStrength':False},'requested':None,'applied':None,
                'outside_supported_range':False,'endgame_factor':endgame_factor}
    if supports:
        option=engine.options['UCI_Elo']
        applied=max(option.min,min(option.max,requested))
        return {'options':{'UCI_LimitStrength':True,'UCI_Elo':applied},'requested':requested,'applied':applied,
                'supported_range':[option.min,option.max], 'outside_supported_range':applied!=requested,
                'endgame_factor':endgame_factor}
    return {'options':{},'requested':requested,'applied':None,'outside_supported_range':True,
            'fallback':'bounded candidate weakening only','endgame_factor':endgame_factor}


def style_score(board, move, style, pv=()):
    """Small deterministic bonuses ONLY inside the permitted quality band."""
    piece=board.piece_at(move.from_square)
    color=board.turn
    child=board.copy(); child.push(move)
    check=board.gives_check(move)
    capture=board.is_capture(move)
    advancement=(chess.square_rank(move.to_square)-chess.square_rank(move.from_square))*(1 if color else -1)
    center=3.5-abs(chess.square_file(move.to_square)-3.5)
    developed=piece.piece_type in (chess.KNIGHT,chess.BISHOP) and chess.square_rank(move.from_square)==(0 if color else 7)
    attacked=[p for sq,p in child.piece_map().items() if p.color!=color and sq in child.attacks(move.to_square) and p.piece_type!=chess.PAWN]
    own_king=child.king(color)
    danger=sum(child.is_attacked_by(not color,sq) for sq in chess.SquareSet(chess.BB_KING_ATTACKS[own_king]))
    if style=='development': return 3*developed+center*.3
    if style=='knight': return (4 if piece.piece_type==chess.KNIGHT and len(attacked)>=2 else 0)+check+center*.2
    if style=='attack': return 3*check+capture+max(0,advancement)*.4+center*.3
    if style=='safety': return 4*board.is_castling(move)-danger*.4+(not child.is_attacked_by(not color,move.to_square))*.5
    if style=='tactical': return 3*check+2*capture+sum('x' in san or '+' in san for san in pv[:4])*.3
    if style=='technical': return (piece.piece_type==chess.KING)*center*.3+max(0,advancement)*.2
    if style=='balanced': return developed+center*.2+board.is_castling(move)
    if style=='positional': return 2*developed+center*.25-danger*.15
    return 0.0


def choose_candidate(board, bot, scored, base_move, seed, endgame_factor=1):
    if not scored:
        raise RuntimeError('No scored candidates')
    best=scored[0]
    cap=bot.max_cp_loss
    outcome_cap=bot.max_outcome_loss
    probability=bot.variety_probability
    if bot.bot_id=='endgame':
        cap=round(cap*max(.15,endgame_factor)); outcome_cap=round(outcome_cap*max(.15,endgame_factor))
        probability*=endgame_factor
    candidates=[]
    for c in scored:
        move=chess.Move.from_uci(c['move'])
        if move not in board.legal_moves: continue
        if best['mate'] is not None and best['mate']>0:
            if c['mate'] is None or c['mate']<=0: continue
        elif c['mate'] is not None and c['mate']<0 and not (best['mate'] is not None and best['mate']<0):
            continue
        if best['outcome_units']-c['outcome_units']>outcome_cap: continue
        if best['cp'] is not None and c['cp'] is not None and best['cp']-c['cp']>cap: continue
        candidates.append(c)
    if not candidates:
        raise RuntimeError('No legal candidate within safety band')
    rng=random.Random(int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8],'big'))
    base=next((c for c in candidates if c['move']==base_move),candidates[0])
    if rng.random()>=probability:
        return base, candidates
    weights=[]
    for index,c in enumerate(candidates):
        score=style_score(board,chess.Move.from_uci(c['move']),bot.style,c.get('pv_san',()))
        # Low bots admit lower-ranked plausible candidates; stronger bots concentrate near PV1.
        temperature=3.0 if bot.bot_id=='scout' else 2.0 if bot.estimated_strength<=1200 else .8
        weights.append(math.exp(-index/temperature+min(3,max(-3,score))*.6))
    return rng.choices(candidates,weights=weights,k=1)[0],candidates


async def bot_move(board, bot_id, seed, snapshot=None):
    if not board.is_valid() or board.is_game_over():
        raise ValueError('Bot requires a valid nonterminal board')
    bot=C.Bot(**{field:snapshot[field] for field in C.Bot.__dataclass_fields__}) if snapshot else C.BOTS[bot_id]
    async def operation(engine):
        strength=strength_settings(bot,engine,board)
        await engine.configure(strength['options'])
        played=await engine.play(board,chess.engine.Limit(time=C.CROWN_SECONDS if bot_id=='crown' else C.BASE_SECONDS,
                                                          depth=C.CROWN_DEPTH if bot_id=='crown' else None),game=object())
        if played.move not in board.legal_moves:
            raise RuntimeError('Engine returned illegal move')
        if bot_id=='crown':
            return {'uci':played.move.uci(),'engine':engine.id,'calibration_version':C.VERSION,'strength_control':strength}
        await engine.configure({'UCI_LimitStrength':False,'Clear Hash':None})
        infos=await engine.analyse(board,chess.engine.Limit(depth=C.ASSESS_DEPTH,time=C.ASSESS_SECONDS),
                                   multipv=min(bot.candidates,board.legal_moves.count()),game=object())
        if not any(i.get('pv',[None])[0]==played.move for i in infos):
            infos.append(await engine.analyse(board,chess.engine.Limit(depth=C.ASSESS_DEPTH,time=C.ASSESS_SECONDS),root_moves=[played.move],game=object()))
        scored=[]
        for info in infos:
            if not info.get('pv') or info['pv'][0] not in board.legal_moves: continue
            position=board.copy(); san=[]
            for move in info['pv'][:6]:
                san.append(position.san(move)); position.push(move)
            scored.append({**outcome(info,board.turn),'move':info['pv'][0].uci(),'pv_san':san,
                           'depth':info.get('depth'),'nodes':info.get('nodes'),'time':info.get('time')})
        scored.sort(key=lambda c:(c['outcome_units'],c['cp'] if c['cp'] is not None else (100000 if c['mate']>0 else -100000)),reverse=True)
        chosen,allowed=choose_candidate(board,bot,scored,played.move.uci(),seed,strength['endgame_factor'])
        return {'uci':chosen['move'],'engine':engine.id,'calibration_version':C.VERSION,
                'strength_control':strength,'assessment_settings':{'depth':C.ASSESS_DEPTH,'time':C.ASSESS_SECONDS},
                'base_move':played.move.uci(),'allowed_candidates':allowed,'selected':chosen}
    return await bounded(operation)


async def recommendation(board):
    async def operation(engine):
        info=await engine.analyse(board,chess.engine.Limit(depth=C.HINT_DEPTH,time=C.HINT_SECONDS),game=object())
        move=info.get('pv',[None])[0]
        if move not in board.legal_moves:
            raise RuntimeError('No legal recommendation')
        return {'uci':move.uci(),'san':board.san(move),'evaluation':outcome(info,board.turn),
                'engine':engine.id,'depth':info.get('depth'),'nodes':info.get('nodes')}
    return await bounded(operation)
