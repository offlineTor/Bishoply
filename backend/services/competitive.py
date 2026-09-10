"""Platform-neutral competitive identity and matchmaking helpers."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from backend.database.db import connect, DEFAULT_RATING_POOL
from backend.services.game_service import STARTING_FEN, CURRENT_RATING_MODEL, build_game_payload


def rating_window(age: float) -> int:
    if age < 10: return 150
    if age < 30: return 300
    if age < 60: return 500
    return min(1200, 500 + int(age - 60) // 15 * 100)


async def ensure_player(platform: str, platform_user_id: str, user_id: int):
    if platform not in {"web", "discord"}:
        raise HTTPException(400, "Unsupported competitive platform")
    db = await connect()
    try:
        row = await (await db.execute("SELECT id FROM competitive_players WHERE platform=? AND platform_user_id=?", (platform, str(platform_user_id)))).fetchone()
        if row:
            await db.execute("UPDATE competitive_players SET user_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (user_id, row["id"]))
            await db.commit()
            return row["id"]
        profile = await (await db.execute("SELECT display_name,username FROM users WHERE id=?", (user_id,))).fetchone()
        if not profile: raise HTTPException(404, "Bishoply profile not found")
        rating = await (await db.execute("SELECT rating FROM skill_ratings WHERE user_id=? AND pool=?", (user_id, DEFAULT_RATING_POOL))).fetchone()
        cursor = await db.execute("INSERT INTO competitive_players(platform,platform_user_id,user_id,display_name,rating) VALUES (?,?,?,?,?) RETURNING id", (platform, str(platform_user_id), user_id, profile["display_name"] or profile["username"], float(rating["rating"]) if rating else 1500.0))
        row = await cursor.fetchone(); await db.commit(); return row["id"]
    except Exception:
        await db.rollback(); raise
    finally: await db.close()


async def join(player_id: int):
    db = await connect()
    try:
        await db.execute("BEGIN IMMEDIATE")
        now = time.time()
        await db.execute("UPDATE competitive_matchmaking_queue SET status='expired',revision=revision+1 WHERE status='queued' AND updated_at<?", (now - 120,))
        me = await (await db.execute("SELECT * FROM competitive_players WHERE id=?", (player_id,))).fetchone()
        if not me: raise HTTPException(404, "Competitive player not found")
        active = await (await db.execute("SELECT public_id FROM games WHERE status='active' AND (white_user_id=? OR black_user_id=?) LIMIT 1", (me["user_id"], me["user_id"]))).fetchone()
        if active: await db.commit(); return {"status":"active_game","game_id":active["public_id"]}
        queued = await (await db.execute("SELECT id FROM competitive_matchmaking_queue WHERE competitive_player_id=? AND status='queued'", (player_id,))).fetchone()
        if queued: raise HTTPException(409, "You are already finding an opponent")
        await db.execute("INSERT INTO competitive_matchmaking_queue(competitive_player_id,rating_snapshot,platform,joined_at,updated_at) VALUES (?,?,?,?,?)", (player_id, me["rating"], me["platform"], now, now))
        candidates = await (await db.execute("SELECT q.*,p.user_id,p.platform,p.rating FROM competitive_matchmaking_queue q JOIN competitive_players p ON p.id=q.competitive_player_id WHERE q.status='queued' AND q.competitive_player_id!=? ORDER BY q.joined_at", (player_id,))).fetchall()
        eligible = [c for c in candidates if abs(float(c["rating"]) - float(me["rating"])) <= rating_window(now-c["joined_at"])]
        chosen = sorted(eligible, key=lambda c: (abs(float(c["rating"])-float(me["rating"])), c["joined_at"]))[0] if eligible else None
        if not chosen:
            await db.commit(); return {"status":"queued","search_seconds":0,"rating_window":rating_window(0)}
        game_id = str(uuid.uuid4())
        white, black = (me["user_id"], chosen["user_id"]) if uuid.uuid4().int % 2 else (chosen["user_id"], me["user_id"])
        await db.execute("INSERT INTO games(public_id,white_user_id,black_user_id,mode,rating_pool,status,starting_fen,current_fen,rated_eligible,integrity_status,rating_model,started_at) VALUES (?,?,?,'casual',?,'active',?,?,1,'pending',?,CURRENT_TIMESTAMP)", (game_id, white, black, DEFAULT_RATING_POOL, STARTING_FEN, STARTING_FEN, CURRENT_RATING_MODEL))
        await db.execute("UPDATE competitive_matchmaking_queue SET status='matched',matched_game_id=?,updated_at=?,revision=revision+1 WHERE competitive_player_id IN (?,?) AND status='queued'", (game_id, now, player_id, chosen["competitive_player_id"]))
        await db.commit()
        return {"status":"matched","game_id":game_id}
    finally: await db.close()


async def status(player_id: int):
    db = await connect()
    try:
        row = await (await db.execute("SELECT * FROM competitive_matchmaking_queue WHERE competitive_player_id=? ORDER BY id DESC LIMIT 1", (player_id,))).fetchone()
        if not row: return {"status":"idle"}
        if row["status"] == "queued": return {"status":"queued","search_seconds":max(0,int(time.time()-row["joined_at"])),"rating_window":rating_window(time.time()-row["joined_at"])}
        if row["status"] == "matched": return {"status":"matched","game_id":row["matched_game_id"]}
        return {"status":"idle"}
    finally: await db.close()


async def cancel(player_id: int):
    db = await connect()
    try:
        await db.execute("UPDATE competitive_matchmaking_queue SET status='cancelled',updated_at=?,revision=revision+1 WHERE competitive_player_id=? AND status='queued'", (time.time(), player_id)); await db.commit()
        return await status(player_id)
    finally: await db.close()
