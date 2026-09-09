"""Practice-only mutations with capability access, atomic turns and stale-job guards."""
import asyncio
import json
import logging
import secrets
import uuid
import chess
from fastapi import HTTPException
from backend.database import db as database
from backend.analysis import service as analysis
from . import bots, config as C, storage

log = logging.getLogger("uvicorn.error")


def check_turn(game, board, ply, actor):
    if game['status']!='active':
        raise HTTPException(409,'Practice game is completed')
    if game['ply']!=ply:
        raise HTTPException(409,'Position changed; reload the game')
    player_turn=('white' if board.turn else 'black')==game['player_color']
    if player_turn!=(actor=='player'):
        raise HTTPException(409,'Not this actor’s turn')


async def create(discord_id, bot_id, color, user_id=None):
    if bot_id not in C.BOTS or color not in ('white','black'):
        raise HTTPException(422,'Unknown bot or color')
    db=await database.connect()
    try:
        await db.execute('BEGIN IMMEDIATE')
        user=await (await db.execute('SELECT id FROM users WHERE id=?' if user_id else 'SELECT id FROM users WHERE discord_id=?',(user_id if user_id else discord_id,))).fetchone()
        if user is None:
            raise HTTPException(404,'Bishoply user not found')
        # Repair legacy duplicate active rows before applying the creation
        # guard.  This keeps the limit meaningful while ensuring a new game
        # can always supersede stale active games transactionally.
        await storage.cleanup_active_games(db, user['id'], int(discord_id) if discord_id is not None else None)
        count=await (await db.execute("SELECT COUNT(*) FROM practice_games WHERE (owner_user_id=? OR owner_discord_id=?) AND status='active'",(user['id'], int(discord_id) if discord_id is not None else None))).fetchone()
        if count[0]>=10:
            raise HTTPException(429,'Finish an existing Practice game before creating another')
        public_id='practice_'+uuid.uuid4().hex
        key=secrets.token_urlsafe(32)
        # Keep the complete calibration snapshot server-side.  The public
        # roster intentionally omits selection controls such as loss bands
        # and candidate variety, but bot_move needs those fields to rebuild
        # the profile for this game.
        bot=C.BOTS[bot_id].public()
        bot_config={field: getattr(C.BOTS[bot_id], field)
                    for field in C.Bot.__dataclass_fields__}
        await db.execute('''INSERT INTO practice_games(public_id,owner_discord_id,owner_user_id,access_hash,player_color,
            bot_id,bot_strength,bot_personality,bot_config,starting_fen,current_fen,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'active')''',(public_id,int(discord_id) if discord_id is not None else None,user['id'],storage.key_hash(key),color,
            bot_id,bot['estimated_strength'],bot['personality'],json.dumps(bot_config),chess.STARTING_FEN,chess.STARTING_FEN))
        await storage.cleanup_active_games(db, user['id'], int(discord_id) if discord_id is not None else None, public_id)
        await db.commit()
        game=await storage.require_game(db,public_id,key)
        log.info("practice_create game=%s bot=%s owner_mode=%s", public_id, bot_id, 'discord' if discord_id is not None else 'web')
        return {**await storage.serialize(db,game),'access_key':key}
    finally:
        await db.close()


async def get(public_id,key=None,owner_user_id=None,owner_discord_id=None):
    db=await database.connect()
    try:
        return await storage.serialize(db,await storage.require_game(db,public_id,key,owner_user_id,owner_discord_id))
    finally:
        await db.close()


async def append_move(db,game,board,move,actor,metadata=None):
    if move not in board.legal_moves:
        raise HTTPException(422,'Illegal move')
    number=board.fullmove_number
    color='white' if board.turn else 'black'
    san=board.san(move)
    assisted=actor=='player' and game['hint_ply']==game['ply'] and game['hint_stage']>0
    hints=game['hint_stage'] if assisted else 0
    board.push(move)
    result=board.outcome(claim_draw=False)
    status='active' if result is None else 'draw' if result.winner is None else 'white_win' if result.winner else 'black_win'
    await db.execute('''INSERT INTO practice_moves(game_id,ply,move_number,color,actor,uci,san,fen_after,assisted,hint_count,bot_metadata)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(game['id'],game['ply']+1,number,color,actor,move.uci(),san,board.fen(),int(assisted),hints,json.dumps(metadata) if metadata else None))
    await db.execute('''UPDATE practice_games SET current_fen=?,ply=ply+1,status=?,result=?,termination_reason=?,
        operation_id=NULL,bot_error=NULL,hint_result=NULL,hint_stage=0,hint_ply=-1,
        completed_at=CASE WHEN ?='active' THEN NULL ELSE CURRENT_TIMESTAMP END,updated_at=CURRENT_TIMESTAMP WHERE id=?''',
        (board.fen(),status,result.result() if result else None,result.termination.name.lower() if result else None,status,game['id']))


async def player_move(public_id,key,uci,ply,owner_user_id=None,owner_discord_id=None):
    log.info("practice_move_received game=%s ply=%s", public_id, ply)
    db=await database.connect()
    try:
        await db.execute('BEGIN IMMEDIATE')
        game=await storage.require_game(db,public_id,key,owner_user_id,owner_discord_id)
        board,_=await storage.load_board(db,game)
        if ply is None:
            ply = int(game['ply'])
        check_turn(game,board,ply,'player')
        if game['operation_id']:
            raise HTTPException(409,'An engine operation is already running')
        if ply>=C.MAX_HISTORY_PLIES:
            raise HTTPException(409,'Practice move limit reached; end this game')
        try: move=chess.Move.from_uci(uci)
        except ValueError: raise HTTPException(422,'Invalid UCI move')
        await append_move(db,game,board,move,'player')
        # Analysis enqueue is part of the same transaction: every accepted player move has a job.
        await analysis.enqueue_feedback(db,public_id,ply+1)
        await db.commit()
    finally:
        await db.close()
    log.info("practice_move game=%s ply=%s", public_id, ply + 1)
    log.info("practice_move_persisted game=%s ply=%s", public_id, ply + 1)
    return {**await get(public_id,key,owner_user_id,owner_discord_id),'analysis':{'status':'queued','ply':ply+1}}


async def claim_operation(public_id,key,ply,actor,owner_user_id=None,owner_discord_id=None):
    db=await database.connect()
    try:
        await db.execute('BEGIN IMMEDIATE')
        game=await storage.require_game(db,public_id,key,owner_user_id,owner_discord_id)
        board,_=await storage.load_board(db,game)
        if ply is None:
            ply = int(game['ply'])
        check_turn(game,board,ply,actor)
        if game['operation_id']:
            raise HTTPException(409,'An engine operation is already running')
        operation=uuid.uuid4().hex
        await db.execute('UPDATE practice_games SET operation_id=?,bot_error=NULL WHERE id=?',(operation,game['id']))
        await db.commit()
        return dict(game),board,operation
    finally:
        await db.close()


async def release_operation(public_id,operation,error=None):
    db=await database.connect()
    try:
        await db.execute('UPDATE practice_games SET operation_id=NULL,bot_error=? WHERE public_id=? AND operation_id=?',(error,public_id,operation))
        await db.commit()
    finally:
        await db.close()


async def bot_response(public_id,key,ply,owner_user_id=None,owner_discord_id=None):
    log.info("practice_bot_requested game=%s ply=%s", public_id, ply)
    game,board,operation=await claim_operation(public_id,key,ply,'bot',owner_user_id,owner_discord_id)
    ply = int(game['ply'])
    claimed_revision = int(game.get('revision', 0))
    error=None
    log.info("Bishoply Practice bot generation started bot=%s side=%s ply=%s", game['bot_id'],
             'white' if board.turn else 'black', ply)
    try:
        metadata=await bots.bot_move(board,game['bot_id'],f'{public_id}:{ply}',json.loads(game['bot_config']))
        log.info("Bishoply Practice bot move selected bot=%s move=%s candidates=%s", game['bot_id'],
                 metadata.get('uci'), len(metadata.get('allowed_candidates', [])))
        log.info("practice_candidate_selected game=%s bot=%s ply=%s", public_id, game['bot_id'], ply)
        move=chess.Move.from_uci(metadata['uci'])
        db=await database.connect()
        try:
            await db.execute('BEGIN IMMEDIATE')
            latest=await storage.require_game(db,public_id,key,owner_user_id,owner_discord_id)
            check_turn(latest,board,ply,'bot')
            if (latest['operation_id']!=operation or
                    int(latest['revision'])!=claimed_revision or
                    latest['current_fen']!=board.fen()):
                raise HTTPException(409,'Position changed during bot search')
            await append_move(db,latest,board,move,'bot',metadata)
            await db.commit()
            log.info("Bishoply Practice bot move persisted bot=%s move=%s", game['bot_id'], move.uci())
            log.info("practice_bot_persisted game=%s bot=%s ply=%s", public_id, game['bot_id'], ply + 1)
        finally:
            await db.close()
    except (asyncio.TimeoutError, chess.engine.EngineError, RuntimeError, ValueError, OSError, KeyError) as exc:
        error='Bot unavailable or timed out; retry bot response'
        log.error("Bishoply Practice bot generation failed type=%s message=%s", type(exc).__name__, str(exc))
        raise HTTPException(503,error) from exc
    finally:
        await release_operation(public_id,operation,error)
    result = await get(public_id,key,owner_user_id,owner_discord_id)
    log.info("Bishoply Practice bot response complete bot=%s ply=%s", game['bot_id'], result.get('ply'))
    log.info("practice_bot_response_sent game=%s bot=%s ply=%s", public_id, game['bot_id'], result.get('ply'))
    return result


def projected_hint(result,stage):
    move=chess.Move.from_uci(result['uci'])
    output={'stage':stage,'concept':'best_move','confidence':'engine_recommendation',
            'piece_square':chess.square_name(move.from_square), 'source_square':chess.square_name(move.from_square)}
    if stage>=2: output['destination']=chess.square_name(move.to_square); output['target_square']=chess.square_name(move.to_square)
    if stage>=3: output.update({'recommended_move':move.uci(),'move_uci':move.uci(),'move_san':result['san'],'san':result['san']})
    return output


async def hint(public_id,key,ply,stage,owner_user_id=None,owner_discord_id=None):
    game,board,operation=await claim_operation(public_id,key,ply,'player',owner_user_id,owner_discord_id)
    try:
        existing=game['hint_stage'] if game['hint_ply']==ply else 0
        if stage>existing+1:
            raise HTTPException(409,'Request the next hint stage in order')
        result=json.loads(game['hint_result']) if game['hint_ply']==ply and game['hint_result'] else await bots.recommendation(board)
        db=await database.connect()
        try:
            await db.execute('BEGIN IMMEDIATE')
            latest=await storage.require_game(db,public_id,key,owner_user_id,owner_discord_id)
            check_turn(latest,board,ply,'player')
            if latest['operation_id']!=operation:
                raise HTTPException(409,'Position changed during hint')
            increment=1 if stage>existing else 0
            await db.execute('''UPDATE practice_games SET hint_count=hint_count+?,assisted=1,hint_ply=?,
                hint_stage=?,hint_result=?,operation_id=NULL WHERE id=?''',(increment,ply,max(stage,existing),json.dumps(result),game['id']))
            await db.commit()
        finally:
            await db.close()
        return {**projected_hint(result,stage),'hint_count':game['hint_count']+increment,'assisted':True,'ply':ply}
    except (asyncio.TimeoutError, chess.engine.EngineError, RuntimeError, ValueError, OSError, KeyError) as exc:
        raise HTTPException(503,'Hint engine unavailable; retry') from exc
    finally:
        await release_operation(public_id,operation)


async def _rebuild_context(db, game_id, max_ply):
    """Restore the newest surviving persisted snapshot after an undo."""
    row = await (await db.execute('''SELECT result FROM analysis_revisions
                        WHERE subject_type='feedback' AND subject_id=(SELECT public_id FROM practice_games WHERE id=?)
                        AND target_ply<=? AND status='complete' ORDER BY target_ply DESC LIMIT 1''', (game_id, max_ply))).fetchone()
    if row and row['result']:
        try:
            result = json.loads(row['result'])
            context = (result.get('intelligence') or {}).get('knowledge', {}).get('coach_context')
            if context:
                await db.execute('''INSERT INTO practice_coach_context(game_id,last_ply,revision,context_json)
                    VALUES (?,?,1,?) ON CONFLICT(game_id) DO UPDATE SET last_ply=excluded.last_ply,
                    revision=excluded.revision,context_json=excluded.context_json,updated_at=CURRENT_TIMESTAMP''',
                    (game_id, max_ply, json.dumps(context, separators=(',', ':'))))
                return
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    await db.execute('DELETE FROM practice_coach_context WHERE game_id=?', (game_id,))


async def undo(public_id, key=None, owner_user_id=None, owner_discord_id=None):
    db = await database.connect()
    try:
        await db.execute('BEGIN IMMEDIATE')
        game = await storage.require_game(db, public_id, key, owner_user_id, owner_discord_id)
        if game['status'] != 'active':
            raise HTTPException(409, 'Completed Practice games cannot be undone')
        rows = await (await db.execute('SELECT * FROM practice_moves WHERE game_id=? ORDER BY ply DESC', (game['id'],))).fetchall()
        if not rows:
            raise HTTPException(409, 'No Practice moves to undo')
        remove = [rows[0]]
        if rows[0]['actor'] == 'bot' and len(rows) > 1 and rows[1]['actor'] == 'player':
            remove.append(rows[1])
        new_ply = int(rows[len(remove) - 1]['ply']) - 1
        await db.execute('DELETE FROM practice_moves WHERE game_id=? AND ply>?', (game['id'], new_ply))
        survivor = await (await db.execute('SELECT fen_after FROM practice_moves WHERE game_id=? ORDER BY ply DESC LIMIT 1', (game['id'],))).fetchone()
        fen = survivor['fen_after'] if survivor else game['starting_fen']
        hints = await (await db.execute('SELECT COALESCE(SUM(hint_count),0),MAX(assisted) FROM practice_moves WHERE game_id=?', (game['id'],))).fetchone()
        await db.execute('''UPDATE practice_games SET current_fen=?,ply=?,revision=revision+1,
            operation_id=NULL,bot_error=NULL,hint_result=NULL,hint_stage=0,hint_ply=-1,
            hint_count=?,assisted=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''',
            (fen, new_ply, int(hints[0] or 0), int(hints[1] or 0), game['id']))
        await db.execute('''UPDATE analysis_revisions SET status='failed',error='Invalidated by Practice undo',updated_at=CURRENT_TIMESTAMP
            WHERE subject_id=? AND ((subject_type='feedback' AND target_ply>?) OR subject_type='practice')
            AND status IN ('queued','analyzing','complete')''', (public_id, new_ply))
        await _rebuild_context(db, game['id'], new_ply)
        await db.commit()
    finally:
        await db.close()
    fresh = await get(public_id, key, owner_user_id, owner_discord_id)
    fresh['removed_plies'] = len(remove)
    fresh['undo_count'] = 1
    return fresh


async def resign(public_id,key=None,owner_user_id=None,owner_discord_id=None):
    db=await database.connect()
    try:
        await db.execute('BEGIN IMMEDIATE')
        game=await storage.require_game(db,public_id,key,owner_user_id,owner_discord_id)
        if game['status']=='active':
            status='black_win' if game['player_color']=='white' else 'white_win'
            await db.execute("UPDATE practice_games SET status=?,result=?,termination_reason='resignation',operation_id=NULL,completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,'0-1' if status=='black_win' else '1-0',game['id']))
        await db.commit()
    finally:
        await db.close()
    return await get(public_id,key,owner_user_id,owner_discord_id)
