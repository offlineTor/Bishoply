"""Durable immutable completed-game review revisions.
Single API process deployment; restart recovery fails interrupted jobs safely.
No user-provided FEN or move enters the engine: only server-stored moves.
"""
import asyncio
from contextlib import closing
import json
import logging
import sqlite3
from fastapi import HTTPException
from backend.database import db as database
from . import config as C
from .worker import run_review, analyze_move
from .engine import Engine
import chess
from backend.chess_knowledge import CoachContext
from backend.chess_knowledge.emma import game_summary

COMPLETE = {'white_win', 'black_win', 'draw'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS game_analysis (
 game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN ('queued','analyzing','complete','failed')),
 progress INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS analysis_revisions (
 id INTEGER PRIMARY KEY, subject_type TEXT NOT NULL CHECK(subject_type IN ('live','practice','feedback')),
 subject_id TEXT NOT NULL, target_ply INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL,
 model_version TEXT NOT NULL, classifier_version TEXT NOT NULL, accuracy_model_version TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','analyzing','complete','failed')),
 progress INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(subject_type,subject_id,target_ply,revision)
);
CREATE INDEX IF NOT EXISTS analysis_queue ON analysis_revisions(status,subject_type,id);
INSERT OR IGNORE INTO analysis_revisions(subject_type,subject_id,revision,model_version,classifier_version,
 accuracy_model_version,status,result)
SELECT 'live',g.public_id,1,'bishoply-outcome-v1','bishoply-outcome-v1','bishoply-outcome-v1','complete',a.result
FROM game_analysis a JOIN games g ON g.id=a.game_id WHERE a.status='complete' AND a.result IS NOT NULL;
"""
_worker = None


def _load_practice_context(db, game_id):
    row = db.execute('SELECT last_ply,revision,context_json FROM practice_coach_context WHERE game_id=?', (game_id,)).fetchone()
    if row is None:
        return CoachContext(), 0, 1
    try:
        return CoachContext.from_dict(json.loads(row['context_json'])), int(row['last_ply']), int(row['revision'])
    except (TypeError, ValueError, json.JSONDecodeError):
        return CoachContext(), 0, int(row['revision'] or 1)


def _save_practice_context(db, game_id, ply, revision, context):
    """Monotonic and idempotent context checkpoint; stale jobs cannot win."""
    current = db.execute('SELECT last_ply,revision FROM practice_coach_context WHERE game_id=?', (game_id,)).fetchone()
    if current is not None and (int(current['revision']) > revision or int(current['last_ply']) >= ply):
        return False
    payload = json.dumps(context.to_dict(), separators=(',', ':'))
    db.execute('''INSERT INTO practice_coach_context(game_id,last_ply,revision,context_json)
                  VALUES (?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET
                  last_ply=excluded.last_ply, revision=excluded.revision,
                  context_json=excluded.context_json, updated_at=CURRENT_TIMESTAMP''',
               (game_id, ply, revision, payload))
    return True


async def initialize():
    global _worker
    db = await database.connect()
    try:
        await db.executescript(SCHEMA)
        await db.execute("UPDATE analysis_revisions SET status='failed',error='Interrupted; request a new revision' WHERE status='analyzing'")
        await db.commit()
    finally:
        await db.close()
    _worker = [asyncio.create_task(work_loop(lane)) for lane in ('fast','deep','feedback')]


async def require_subject(db, public_id, kind='live', key=None):
    if kind == 'live':
        game = await (await db.execute('SELECT * FROM games WHERE public_id=?', (public_id,))).fetchone()
        if game is None:
            raise HTTPException(404, 'Game not found')
    else:
        from backend.practice.storage import require_game
        if key is None:
            raise HTTPException(401, 'Practice access key required')
        game = await require_game(db, public_id, key)
    if kind != 'feedback' and game['status'] not in COMPLETE:
        raise HTTPException(409, 'Game Review requires a completed game')
    return game


async def enqueue_feedback(db, public_id, ply):
    """Caller owns the move transaction; no accepted move loses its analysis job."""
    game = await (await db.execute("SELECT id FROM practice_games WHERE public_id=? AND mode='practice'",(public_id,))).fetchone()
    if game is None:
        raise HTTPException(403, 'Practice mode required')
    move = await (await db.execute("SELECT id FROM practice_moves WHERE game_id=? AND ply=? AND actor='player'",(game['id'],ply))).fetchone()
    if move is None:
        raise HTTPException(404, 'Played player move required')
    count = await (await db.execute("SELECT COUNT(*) FROM analysis_revisions WHERE subject_type='feedback' AND status IN ('queued','analyzing')")).fetchone()
    if count[0] >= 32:
        raise HTTPException(429, 'Practice analysis queue full; retry your move shortly')
    await db.execute("""INSERT INTO analysis_revisions(subject_type,subject_id,target_ply,revision,
        model_version,classifier_version,accuracy_model_version,status)
        VALUES ('feedback',?,?,1,?,?,?,'queued')""",(public_id,ply,C.MODEL_VERSION,C.CLASSIFIER_VERSION,C.ACCURACY_VERSION))


def decoded(row, total=0):
    result = json.loads(row['result']) if row['result'] else None
    # Keep full search evidence in SQLite; avoid retransmitting both pass trees
    # for every ply on every progress poll. Practice feedback keeps its contract.
    if result and row['subject_type'] != 'feedback':
        for move in result.get('moves', []):
            if 'verification' in move:
                move['verification'] = {k:v for k,v in move['verification'].items()
                                        if k not in ('normal_pass','authoritative_pass')}
    stage = result.get('stage') if result else None
    status = stage if row['status'] == 'analyzing' and stage in ('fast_analysis','deep_analysis') else row['status']
    return {'status': status, 'progress': row['progress'], 'error': row['error'],
            'analysis_revision': row['revision'], 'result': result,
            'analyzed_plies': result.get('analyzed_plies', 0) if result else 0,
            'total_plies': result.get('total_plies', total) if result else total,
            'percentage': result.get('percentage', 0) if result else 0}


async def get_review(public_id, enqueue=False, *, new_revision=False, kind='live', ply=0, key=None):
    if kind not in ('live','practice','feedback'):
        raise HTTPException(400, 'Invalid analysis kind')
    db = await database.connect()
    try:
        game = await require_subject(db, public_id, kind, key)
        if kind == 'feedback':
            move = await (await db.execute("SELECT id FROM practice_moves WHERE game_id=? AND ply=? AND actor='player'",(game['id'],ply))).fetchone()
            if move is None:
                raise HTTPException(404, 'Played player move required')
        move_table = 'game_moves' if kind == 'live' else 'practice_moves'
        total = 1 if kind == 'feedback' else (await (await db.execute(f'SELECT COUNT(*) FROM {move_table} WHERE game_id=?',(game['id'],))).fetchone())[0]
        if enqueue:
            await db.execute('BEGIN IMMEDIATE')
        params=(kind,public_id,ply)
        rows = await (await db.execute('SELECT * FROM analysis_revisions WHERE subject_type=? AND subject_id=? AND target_ply=? ORDER BY revision DESC',params)).fetchall()
        current=next((r for r in rows if r['model_version']==C.MODEL_VERSION and r['classifier_version']==C.CLASSIFIER_VERSION and r['accuracy_model_version']==C.ACCURACY_VERSION),None)
        if enqueue and (current is None or current['status']=='failed' or (new_revision and current['status']=='complete')):
            pending=await (await db.execute("SELECT COUNT(*) FROM analysis_revisions WHERE subject_type=? AND status IN ('queued','analyzing')",(kind,))).fetchone()
            if pending[0] >= (32 if kind == 'feedback' else 8):
                raise HTTPException(429,'Analysis queue full; retry later')
            revision=rows[0]['revision']+1 if rows else 1
            await db.execute('''INSERT INTO analysis_revisions(subject_type,subject_id,target_ply,revision,
                model_version,classifier_version,accuracy_model_version,status) VALUES (?,?,?,?,?,?,?,'queued')''',
                (*params,revision,C.MODEL_VERSION,C.CLASSIFIER_VERSION,C.ACCURACY_VERSION))
            await db.commit()
            return {'status':'queued','progress':0,'analysis_revision':revision,'result':None,'analyzed_plies':0,'total_plies':total,'percentage':0}
        if enqueue:
            await db.commit()
        # Old records remain for audit, but a changed model requires a new review.
        if current is None:
            return {'status':'not_started','previous_revisions':len(rows),'analyzed_plies':0,'total_plies':total,'percentage':0}
        if current['status'] in ('queued','analyzing','failed'):
            authoritative=next((r for r in rows if r['status']=='complete' and r['model_version']==C.MODEL_VERSION and r['classifier_version']==C.CLASSIFIER_VERSION and r['accuracy_model_version']==C.ACCURACY_VERSION),None)
            if authoritative:
                return {**decoded(authoritative,total),'pending_revision':current['revision'],'pending_status':current['status']}
        return decoded(current,total)
    finally:
        await db.close()


def process_one(lane=None):
    if lane not in (None,'review','feedback','fast','deep'):
        raise ValueError('Invalid worker lane')
    db = database.sync_connect()
    with closing(db):
        db.execute('BEGIN IMMEDIATE')
        clause = "AND subject_type='feedback'" if lane=='feedback' else "AND subject_type!='feedback'" if lane in ('review','fast','deep') else ""
        if lane == 'fast':
            clause += (" AND COALESCE((result::jsonb ->> 'stage'),'') != 'deep_queued'"
                       if database.using_postgres() else " AND COALESCE(json_extract(result,'$.stage'),'') != 'deep_queued'")
        if lane == 'deep':
            clause += (" AND (result::jsonb ->> 'stage') = 'deep_queued'"
                       if database.using_postgres() else " AND json_extract(result,'$.stage') = 'deep_queued'")
        row=db.execute(f"SELECT * FROM analysis_revisions WHERE status='queued' {clause} ORDER BY id LIMIT 1").fetchone()
        if row is None:
            db.commit(); return False
        db.execute("UPDATE analysis_revisions SET status='analyzing',updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['id'],))
        db.commit()
        try:
            practice=row['subject_type']!='live'
            table='practice_games' if practice else 'games'
            move_table='practice_moves' if practice else 'game_moves'
            game=dict(db.execute(f'SELECT * FROM {table} WHERE public_id=?',(row['subject_id'],)).fetchone())
            if practice and game['mode']!='practice':
                raise ValueError('Practice mode required')
            if row['subject_type']!='feedback' and game['status'] not in COMPLETE:
                raise ValueError('Completed game required')
            moves=[dict(m) for m in db.execute(f'SELECT * FROM {move_table} WHERE game_id=? ORDER BY ply',(game['id'],))]
            game['analysis_revision']=row['revision']
            def progress(ply):
                db.execute('UPDATE analysis_revisions SET progress=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(ply,row['id']))
                db.commit()
            if row['subject_type']=='feedback':
                board=chess.Board(game['starting_fen'])
                target=next(m for m in moves if m['ply']==row['target_ply'] and m['actor']=='player')
                for previous in moves:
                    if previous['ply']>=target['ply']: break
                    board.push_uci(previous['uci'])
                    if board.fen()!=previous['fen_after']:
                        raise ValueError('Stored Practice replay mismatch')
                with Engine() as engine:
                    context, context_ply, context_revision = _load_practice_context(db, game['id'])
                    result=analyze_move(engine,board,chess.Move.from_uci(target['uci']),practice=True,
                        revision=row['revision'],assisted=bool(target['assisted']),preliminary=True,
                        coach_context=context, ply=int(target['ply']))
                    result['provenance']=engine.provenance
                    result['ply']=target['ply']
                    if isinstance(result.get('intelligence'), dict): result['intelligence']['ply'] = target['ply']
                    result['hint_count']=target['hint_count']
                    _save_practice_context(db, game['id'], int(target['ply']), int(row['revision']), context)
                if result['fen']!=target['fen_after']:
                    raise ValueError('Practice feedback position mismatch')
            else:
                def publish(partial):
                    latest = db.execute(f'SELECT mode,status FROM {table} WHERE id=?',(game['id'],)).fetchone()
                    if latest['status'] not in COMPLETE or (practice and latest['mode'] != 'practice'):
                        raise PermissionError('Completed game required for publication')
                    db.execute('UPDATE analysis_revisions SET result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                               (json.dumps(partial),row['id']))
                    db.commit()
                options = {'tiers': (True,)} if lane == 'fast' else {'tiers': (False,), 'initial_result': json.loads(row['result'])} if lane == 'deep' else {}
                result=run_review(game,moves,progress,publish=publish,**options)
            latest=db.execute(f'SELECT mode,status FROM {table} WHERE id=?',(game['id'],)).fetchone()
            if practice and latest['mode']!='practice':
                raise ValueError('Practice mode required')
            if row['subject_type']!='feedback' and latest['status'] not in COMPLETE:
                raise ValueError('Game no longer completed')
            db.execute("UPDATE analysis_revisions SET status=?,result=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                ('queued' if result.get('stage')=='deep_queued' else 'failed' if result.get('stage')=='failed' else 'complete',json.dumps(result),
                 'Some moves could not be verified; partial review remains available.' if result.get('stage')=='failed' else None,row['id']))
        except Exception:
            logging.exception('Analysis revision %s failed',row['id'])
            db.execute("UPDATE analysis_revisions SET status='failed',error='Analysis could not be verified. Retry or inspect server logs.',updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['id'],))
        db.commit()
        return True


async def work_loop(lane=None):
    while True:
        try:
            if not await asyncio.to_thread(process_one, lane):
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception('Review queue error')
            await asyncio.sleep(3)
