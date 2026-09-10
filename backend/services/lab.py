"""Authenticated saved positions for Bishoply Lab; never creates game history."""
import chess
import chess.engine
from fastapi import HTTPException
from backend.database.db import connect
from backend.practice.bots import bounded

def _valid_fen(fen):
    try: chess.Board(fen)
    except Exception as exc: raise HTTPException(422, "Invalid FEN position") from exc
    return fen

async def create(user_id, name, fen):
    fen = _valid_fen(fen); name = str(name or "Untitled position").strip()[:80] or "Untitled position"
    db = await connect()
    try:
        row = await (await db.execute("INSERT INTO saved_lab_positions(user_id,name,fen) VALUES (?,?,?) RETURNING id, name, fen, created_at, updated_at", (user_id,name,fen))).fetchone(); await db.commit(); return dict(row)
    finally: await db.close()

async def list_for_user(user_id):
    db = await connect()
    try: return [dict(row) for row in await (await db.execute("SELECT id,name,fen,created_at,updated_at FROM saved_lab_positions WHERE user_id=? ORDER BY updated_at DESC,id DESC", (user_id,))).fetchall()]
    finally: await db.close()

async def delete(user_id, position_id):
    db = await connect()
    try:
        result = await db.execute("DELETE FROM saved_lab_positions WHERE id=? AND user_id=?", (position_id,user_id)); await db.commit()
        if not result.rowcount: raise HTTPException(404, "Lab position not found")
        return {"deleted": True}
    finally: await db.close()

async def rename(user_id, position_id, name):
    db = await connect()
    try:
        result = await db.execute("UPDATE saved_lab_positions SET name=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?", (str(name or "Untitled position").strip()[:80], position_id, user_id)); await db.commit()
        if not result.rowcount: raise HTTPException(404, "Lab position not found")
        return {"updated": True}
    finally: await db.close()

async def analyze(fen, depth=None):
    board = chess.Board(_valid_fen(fen)); depth = max(8, min(int(depth or 12), 24))
    async def job(engine):
        info = await engine.analyse(board, chess.engine.Limit(depth=depth), multipv=3)
        rows=[]
        for item in info if isinstance(info,list) else [info]:
            score=item.get("score").pov(board.turn); rows.append({"move": item["pv"][0].uci() if item.get("pv") else None, "pv": [m.uci() for m in item.get("pv",[])], "evaluation": score.score(), "mate": score.mate(), "depth": item.get("depth")})
        return {"fen": board.fen(), "candidates": rows, "best_move": rows[0]["move"] if rows else None}
    return await bounded(job)

async def bot_move(fen, bot_id="scout"):
    board = chess.Board(_valid_fen(fen))
    async def job(engine):
        result = await engine.play(board, chess.engine.Limit(depth=12)); move=result.move
        san=board.san(move); board.push(move)
        return {"move": move.uci(), "san": san, "fen_after": board.fen(), "bot_id": bot_id}
    return await bounded(job)
