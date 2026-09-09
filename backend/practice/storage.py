"""Practice owns its tables; no FK or mutation into competitive profiles."""
import hashlib
import hmac
import json
import chess
import logging
from fastapi import HTTPException
from backend.database import db as database
from . import config as C
log = logging.getLogger('uvicorn.error')

SCHEMA = """
CREATE TABLE IF NOT EXISTS practice_games (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 public_id TEXT NOT NULL UNIQUE,
 mode TEXT NOT NULL DEFAULT 'practice' CHECK(mode='practice'),
 owner_discord_id BIGINT,
 owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
 access_hash TEXT NOT NULL,
 player_color TEXT NOT NULL CHECK(player_color IN ('white','black')),
 bot_id TEXT NOT NULL,
 bot_strength INTEGER NOT NULL,
 bot_personality TEXT NOT NULL,
 bot_config TEXT NOT NULL,
 starting_fen TEXT NOT NULL,
 current_fen TEXT NOT NULL,
 ply INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK(status IN ('active','white_win','black_win','draw')),
 result TEXT,
 termination_reason TEXT,
 hint_count INTEGER NOT NULL DEFAULT 0,
 assisted INTEGER NOT NULL DEFAULT 0,
 hint_ply INTEGER NOT NULL DEFAULT -1,
 hint_stage INTEGER NOT NULL DEFAULT 0,
 hint_result TEXT,
 operation_id TEXT,
 bot_error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 completed_at TEXT
);
CREATE TABLE IF NOT EXISTS practice_moves (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 game_id INTEGER NOT NULL REFERENCES practice_games(id) ON DELETE CASCADE,
 ply INTEGER NOT NULL,
 move_number INTEGER NOT NULL,
 color TEXT NOT NULL CHECK(color IN ('white','black')),
 actor TEXT NOT NULL CHECK(actor IN ('player','bot')),
 uci TEXT NOT NULL,
 san TEXT NOT NULL,
 fen_after TEXT NOT NULL,
 assisted INTEGER NOT NULL DEFAULT 0,
 hint_count INTEGER NOT NULL DEFAULT 0,
 bot_metadata TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(game_id,ply)
);
CREATE INDEX IF NOT EXISTS practice_history ON practice_games(owner_discord_id,created_at);
CREATE TABLE IF NOT EXISTS practice_coach_context (
 game_id INTEGER PRIMARY KEY REFERENCES practice_games(id) ON DELETE CASCADE,
 last_ply INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1,
 context_json TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


async def initialize():
    db=await database.connect()
    try:
        await db.executescript(SCHEMA)
        columns = await database.get_table_columns(db, "practice_games")
        if "revision" not in columns:
            await db.execute("ALTER TABLE practice_games ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        if "owner_user_id" not in columns:
            await db.execute("ALTER TABLE practice_games ADD COLUMN owner_user_id INTEGER")
        if database.using_postgres():
            await db.execute("ALTER TABLE practice_games ALTER COLUMN owner_discord_id DROP NOT NULL")
        # CREATE TABLE IF NOT EXISTS cannot alter a pre-Accounts production
        # table. Create the dependent index only after the additive column
        # migration has completed, then safely associate legacy Discord rows
        # with canonical users where the mapping is unambiguous.
        await db.execute("""UPDATE practice_games
            SET owner_user_id=(SELECT id FROM users WHERE users.discord_id=practice_games.owner_discord_id)
            WHERE owner_user_id IS NULL AND owner_discord_id IS NOT NULL""")
        await db.execute("CREATE INDEX IF NOT EXISTS practice_history_user ON practice_games(owner_user_id,created_at)")
        users = await (await db.execute("SELECT id,discord_id FROM users")).fetchall()
        for user in users:
            await cleanup_active_games(db, user['id'], user['discord_id'])
        await db.execute("UPDATE practice_games SET operation_id=NULL,bot_error='Operation interrupted; retry' WHERE operation_id IS NOT NULL")
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def cleanup_active_games(db, user_id, discord_id=None, keep_public_id=None):
    rows = await (await db.execute("""SELECT id,public_id FROM practice_games
        WHERE status='active' AND (owner_user_id=? OR (? IS NOT NULL AND owner_discord_id=?))
        ORDER BY created_at DESC,id DESC""", (user_id, discord_id, discord_id))).fetchall()
    if keep_public_id:
        rows = sorted(rows, key=lambda row: row['public_id'] == keep_public_id, reverse=True)
    if len(rows) <= 1: return rows[0] if rows else None
    kept = rows[0]
    for row in rows[1:]:
        await db.execute("UPDATE practice_games SET status='draw',result=NULL,termination_reason='superseded',completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP,operation_id=NULL WHERE id=? AND status='active'", (row['id'],))
    log.info('practice_active_cleanup user_id=%s kept_game=%s superseded_count=%s', user_id, kept['public_id'], len(rows)-1)
    return kept


async def require_game(db, public_id, key=None, owner_user_id=None, owner_discord_id=None):
    game=await (await db.execute('SELECT * FROM practice_games WHERE public_id=?',(public_id,))).fetchone()
    if game is None:
        raise HTTPException(404,'Practice game not found')
    if game['mode']!='practice':
        raise HTTPException(403,'Practice mode required')
    if key is not None and not hmac.compare_digest(key_hash(key),game['access_hash']):
        raise HTTPException(403,'Invalid Practice access key')
    if key is None and owner_user_id is not None:
        owned = game['owner_user_id'] == owner_user_id or (
            owner_discord_id is not None and game['owner_discord_id'] == owner_discord_id)
        if not owned:
            raise HTTPException(403, 'Practice game access denied')
    elif key is None and owner_user_id is None:
        raise HTTPException(401, 'Practice access key required')
    return game


async def load_board(db,game):
    moves=await (await db.execute('SELECT * FROM practice_moves WHERE game_id=? ORDER BY ply',(game['id'],))).fetchall()
    board=chess.Board(game['starting_fen'])
    for row in moves:
        move=chess.Move.from_uci(row['uci'])
        if move not in board.legal_moves:
            raise RuntimeError('Invalid stored Practice move')
        board.push(move)
        if board.fen()!=row['fen_after']:
            raise RuntimeError('Invalid stored Practice position')
    if board.fen()!=game['current_fen'] or len(moves)!=game['ply']:
        raise RuntimeError('Practice position snapshot mismatch')
    return board,moves


async def serialize(db, game):
    board,moves=await load_board(db,game)
    turn='white' if board.turn else 'black'
    return {'game_id':game['public_id'],'mode':'practice','unrated':True,'player_color':game['player_color'],
            # bot_config contains private calibration controls used only by
            # the server.  Keep the response on the public roster contract.
            'bot':C.BOTS[game['bot_id']].public(),
            'status':game['status'],'result':game['result'],'termination_reason':game['termination_reason'],
            'fen':game['current_fen'],'ply':game['ply'],'revision':game['revision'] if 'revision' in game.keys() else 0,'turn':turn,
            'needs_bot_move':game['status']=='active' and turn!=game['player_color'],
            'busy':bool(game['operation_id']),'bot_error':game['bot_error'],
            'hint_count':game['hint_count'],'assisted':bool(game['assisted']),
            'legal_moves':[{'uci':m.uci(),'from':chess.square_name(m.from_square),'to':chess.square_name(m.to_square),
                            'promotion':chess.piece_name(m.promotion) if m.promotion else None} for m in board.legal_moves]
                          if game['status']=='active' and turn==game['player_color'] else [],
            'moves':[{k:row[k] for k in ('ply','move_number','color','actor','uci','san','fen_after','assisted','hint_count')} for row in moves],
            'created_at':game['created_at'],'completed_at':game['completed_at']}
