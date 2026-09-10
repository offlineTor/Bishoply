"""Authenticated Duel matchmaking backed by a small, lock-friendly SQLite queue."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from backend.database.db import connect, DEFAULT_RATING_POOL, ensure_competitive_profile
from backend.services.game_service import STARTING_FEN, CURRENT_RATING_MODEL, build_game_payload
from backend.services import competitive

SCHEMA = """
CREATE TABLE IF NOT EXISTS matchmaking_queue (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 discord_user_id BIGINT NOT NULL,
 queue_type TEXT NOT NULL DEFAULT 'duel',
 rating_snapshot REAL NOT NULL,
 joined_at REAL NOT NULL,
 updated_at REAL NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','matched','cancelled','expired')),
 matched_game_id TEXT,
 revision INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS matchmaking_waiting ON matchmaking_queue(queue_type,status,joined_at);
CREATE INDEX IF NOT EXISTS matchmaking_rating ON matchmaking_queue(queue_type,status,rating_snapshot);
CREATE UNIQUE INDEX IF NOT EXISTS matchmaking_one_queued ON matchmaking_queue(discord_user_id,queue_type) WHERE status='queued';
"""
STALE_SECONDS = 120

# Generic platform-neutral queue used by Web and Activity clients. The legacy
# Discord queue below remains available for existing clients during migration.
async def join_generic(player_id):
    return await competitive.join(player_id)

async def status_generic(player_id):
    return await competitive.status(player_id)

async def cancel_generic(player_id):
    return await competitive.cancel(player_id)


async def initialize():
    db = await connect()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


def _window(age):
    if age < 5: return 150
    if age < 15: return 300
    if age < 30: return 500
    return min(1200, 500 + int(age - 30) // 10 * 100)


async def _profile(db, discord_id):
    row = await (await db.execute("SELECT id,discord_id,username,display_name,avatar_url FROM users WHERE discord_id=?", (int(discord_id),))).fetchone()
    if row is None:
        raise HTTPException(404, "Bishoply profile not found")
    await ensure_competitive_profile(db, row["id"])
    rating = await (await db.execute("SELECT rating FROM skill_ratings WHERE user_id=? AND pool=?", (row["id"], DEFAULT_RATING_POOL))).fetchone()
    return row, int(round(float(rating["rating"]))) if rating else 1200


def _opponent(row):
    if not row: return None
    return {key: row[key] for key in ("display_name", "username", "avatar_url")}


async def _state(db, user_id, now=None):
    now = now or time.time()
    row = await (await db.execute("SELECT * FROM matchmaking_queue WHERE discord_user_id=? AND queue_type='duel' AND status='queued' ORDER BY id DESC LIMIT 1", (int(user_id),))).fetchone()
    if row:
        age = max(0, int(now - row["joined_at"]))
        return {"status":"queued", "joined_at":datetime.fromtimestamp(row["joined_at"], timezone.utc).isoformat(), "search_seconds":age, "rating_window":_window(age)}
    row = await (await db.execute("SELECT * FROM matchmaking_queue WHERE discord_user_id=? AND queue_type='duel' AND status='matched' ORDER BY id DESC LIMIT 1", (int(user_id),))).fetchone()
    if not row:
        active = await (await db.execute("SELECT public_id FROM games WHERE status='active' AND (white_user_id=(SELECT id FROM users WHERE discord_id=?) OR black_user_id=(SELECT id FROM users WHERE discord_id=?)) LIMIT 1", (int(user_id), int(user_id)))).fetchone()
        return {"status":"active_game", "game_id":active["public_id"]} if active else {"status":"idle"}
    game = await (await db.execute("SELECT * FROM games WHERE public_id=?", (row["matched_game_id"],))).fetchone()
    if not game: return {"status":"idle"}
    payload = await build_game_payload(db, game)
    color = "white" if str((payload.get("white") or {}).get("discord_id")) == str(user_id) else "black"
    opponent = payload.get("black") if color == "white" else payload.get("white")
    return {"status":"matched", "game_id":row["matched_game_id"], "player_color":color, "opponent":_opponent(opponent)}


async def join(user_id):
    db = await connect()
    try:
        await db.execute("BEGIN IMMEDIATE")
        now = time.time()
        await db.execute("UPDATE matchmaking_queue SET status='expired',revision=revision+1 WHERE queue_type='duel' AND status='queued' AND updated_at<?", (now - STALE_SECONDS,))
        row, rating = await _profile(db, user_id)
        active = await (await db.execute("SELECT public_id FROM games WHERE status='active' AND (white_user_id=? OR black_user_id=?) LIMIT 1", (row["id"], row["id"]))).fetchone()
        if active:
            await db.commit()
            return {"status":"active_game", "game_id":active["public_id"]}
        existing = await (await db.execute("SELECT * FROM matchmaking_queue WHERE discord_user_id=? AND queue_type='duel' AND status='queued'", (int(user_id),))).fetchone()
        if existing: raise HTTPException(409, "You are already finding an opponent")
        await db.execute("INSERT INTO matchmaking_queue(discord_user_id,rating_snapshot,joined_at,updated_at,status) VALUES (?,?,?,?, 'queued')", (int(user_id), rating, now, now))
        mine = await (await db.execute("SELECT id FROM matchmaking_queue WHERE discord_user_id=? AND queue_type='duel' AND status='queued'", (int(user_id),))).fetchone()
        candidate_sql = "SELECT q.*,u.id AS uid,u.display_name,u.username,u.avatar_url FROM matchmaking_queue q JOIN users u ON u.discord_id=q.discord_user_id WHERE q.queue_type='duel' AND q.status='queued' AND q.discord_user_id!=?"
        if getattr(db, "backend", "sqlite") == "postgres":
            candidate_sql += " ORDER BY q.joined_at FOR UPDATE SKIP LOCKED"
        candidate = await (await db.execute(candidate_sql, (int(user_id),))).fetchall()
        eligible = [item for item in candidate if abs(float(item["rating_snapshot"]) - rating) <= max(_window(now-item["joined_at"]), 150)]
        eligible.sort(key=lambda item: (abs(float(item["rating_snapshot"]) - rating), item["joined_at"]))
        chosen = eligible[0] if eligible else None
        if chosen:
            white_id, black_id = (row["id"], chosen["uid"]) if uuid.uuid4().int % 2 else (chosen["uid"], row["id"])
            game_id = str(uuid.uuid4())
            await db.execute("INSERT INTO games(public_id,white_user_id,black_user_id,mode,rating_pool,status,starting_fen,current_fen,rated_eligible,integrity_status,rating_model,started_at) VALUES (?,?,?,'casual',?,'active',?,?,1,'pending',?,CURRENT_TIMESTAMP)", (game_id,white_id,black_id,DEFAULT_RATING_POOL,STARTING_FEN,STARTING_FEN,CURRENT_RATING_MODEL))
            reserved = await db.execute("UPDATE matchmaking_queue SET status='matched',matched_game_id=?,updated_at=?,revision=revision+1 WHERE id IN (?,?) AND status='queued'", (game_id,now,mine["id"],chosen["id"]))
            if getattr(reserved, "rowcount", 2) != 2:
                await db.rollback()
                return {"status": "queued", "search_seconds": 0, "rating_window": _window(0)}
        await db.commit()
        return await _state(db, user_id, now)
    finally:
        await db.close()


async def status(user_id):
    db = await connect()
    try: return await _state(db, user_id)
    finally: await db.close()


async def cancel(user_id):
    db = await connect()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute("SELECT * FROM matchmaking_queue WHERE discord_user_id=? AND queue_type='duel' ORDER BY id DESC LIMIT 1", (int(user_id),))).fetchone()
        if row and row["status"] == "queued":
            await db.execute("UPDATE matchmaking_queue SET status='cancelled',updated_at=?,revision=revision+1 WHERE id=? AND status='queued'", (time.time(), row["id"]))
        await db.commit()
        return await _state(db, user_id)
    finally: await db.close()
