import re
from fastapi import APIRouter, HTTPException, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from backend import accounts
from backend.database import db
from backend.practice.auth import discord_identity
from backend.services.profile_service import get_profile_by_discord_id

router = APIRouter(prefix="/api/profile", tags=["profile"])
USERNAME = re.compile(r"^[A-Za-z0-9_]{3,20}$")
RESERVED = {"admin", "bishoply", "support", "moderator", "system", "bot"}

async def owner(request: Request, authorization: str | None = Header(None)):
    if authorization:
        discord_id = await discord_identity(authorization)
        row = await _one("SELECT id FROM users WHERE discord_id=?", (discord_id,))
        if not row: raise HTTPException(404, "Bishoply profile not found")
        return row["id"]
    return await accounts.session_user(request)

async def _one(sql, params=()):
    connection = await db.connect()
    try: return await (await connection.execute(sql, params)).fetchone()
    finally: await connection.close()

async def profile_for(user_id):
    row = await _one("SELECT id,discord_id,username,email,display_name,avatar_url,created_at,username_selected_at,username_change_count FROM users WHERE id=?", (user_id,))
    if not row: raise HTTPException(404, "Bishoply profile not found")
    rating = await _one("SELECT rating,peak_rating,rating_deviation,provisional,wins,losses,draws,games_played,rated_games FROM ratings WHERE user_id=?", (user_id,))
    progression = await _one("SELECT sr,peak_sr,games_rewarded FROM progression WHERE user_id=?", (user_id,))
    return {"user_id": row["id"], "discord_id": row["discord_id"], "username": row["username"], "email": row["email"], "username_selected": bool(row["username_selected_at"]), "display_name": row["display_name"], "avatar_url": row["avatar_url"], "account_created_at": row["created_at"], "rating": round(float(rating["rating"])) if rating else 1200, "peak_rating": round(float(rating["peak_rating"])) if rating else 1200, "sr": int(progression["sr"]) if progression else 2500, "peak_sr": int(progression["peak_sr"]) if progression else 2500, "wins": int(rating["wins"]) if rating else 0, "losses": int(rating["losses"]) if rating else 0, "draws": int(rating["draws"]) if rating else 0, "games_played": int(rating["games_played"]) if rating else 0}

@router.get("")
async def read_current_profile(request: Request, authorization: str | None = Header(None)):
    return await profile_for(await owner(request, authorization))

@router.get("/username/availability")
async def username_availability(username: str = Query(..., min_length=3, max_length=20)):
    normalized = username.strip().lower()
    if not USERNAME.fullmatch(username) or normalized in RESERVED: return {"available": False}
    return {"available": (await _one("SELECT id FROM users WHERE username_normalized=?", (normalized,))) is None}

class UsernameRequest(BaseModel): username: str = Field(min_length=3, max_length=20)

@router.post("/username")
async def set_username(payload: UsernameRequest, request: Request, authorization: str | None = Header(None)):
    user_id = await owner(request, authorization); value = payload.username.strip(); normalized = value.lower()
    if not USERNAME.fullmatch(value) or normalized in RESERVED: raise HTTPException(422, "Username is not available")
    connection = await db.connect()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        row = await (await connection.execute("SELECT username,username_selected_at,username_change_count FROM users WHERE id=?", (user_id,))).fetchone()
        existing = await (await connection.execute("SELECT id FROM users WHERE username_normalized=? AND id<>?", (normalized,user_id))).fetchone()
        if existing: raise HTTPException(409, "Username is already taken")
        if row["username_selected_at"] and int(row["username_change_count"] or 0) > 0:
            raise HTTPException(402, "Username changes require checkout")
        await connection.execute("INSERT INTO username_history(user_id,old_username,new_username) VALUES (?,?,?)", (user_id,row["username"],value))
        await connection.execute("UPDATE users SET username=?,username_normalized=?,username_selected_at=CURRENT_TIMESTAMP WHERE id=?", (value,normalized,user_id)); await connection.commit()
    except Exception:
        await connection.rollback(); raise
    finally: await connection.close()
    return await profile_for(user_id)

@router.post("/username/change-intent")
async def username_change_intent(payload: UsernameRequest, request: Request, authorization: str | None = Header(None)):
    user_id = await owner(request, authorization); normalized = payload.username.strip().lower()
    if not USERNAME.fullmatch(payload.username) or normalized in RESERVED: raise HTTPException(422, "Username is not available")
    row = await _one("SELECT username_selected_at,username_change_count FROM users WHERE id=?", (user_id,))
    if not row or not row["username_selected_at"]: raise HTTPException(409, "Choose your first username before purchasing a rename")
    if await _one("SELECT id FROM users WHERE username_normalized=? AND id<>?", (normalized,user_id)): raise HTTPException(409, "Username is already taken")
    raise HTTPException(503, "Username checkout is not configured")

@router.get("/cosmetics")
async def cosmetics(request: Request, authorization: str | None = Header(None)):
    user_id = await owner(request, authorization)
    rows = await _all("SELECT c.id,c.sku,c.name,c.category,c.rarity,c.metadata_json FROM cosmetics c JOIN user_cosmetics u ON u.cosmetic_id=c.id WHERE u.user_id=? AND c.active=1", (user_id,))
    loadout = await _one("SELECT * FROM user_loadout WHERE user_id=?", (user_id,))
    return {"owned": [dict(r) for r in rows], "loadout": dict(loadout) if loadout else {}}

@router.put("/loadout")
async def update_loadout(payload: dict, request: Request, authorization: str | None = Header(None)):
    user_id = await owner(request, authorization)
    slots = ('board_skin_id','piece_set_id','board_border_id','profile_frame_id','background_effect_id','move_sound_id','capture_sound_id','check_sound_id','victory_sound_id','sound_pack_id')
    values = {slot: payload.get(slot) for slot in slots}
    categories = {'board_skin_id':'board_skin','piece_set_id':'piece_set','board_border_id':'board_border','profile_frame_id':'profile_frame','background_effect_id':'background_effect','move_sound_id':'move_sound','capture_sound_id':'capture_sound','check_sound_id':'check_sound','victory_sound_id':'victory_sound','sound_pack_id':'sound_pack'}
    connection = await db.connect()
    try:
        for slot, cosmetic_id in values.items():
            if cosmetic_id is None: continue
            row = await (await connection.execute("SELECT c.id FROM cosmetics c JOIN user_cosmetics u ON u.cosmetic_id=c.id WHERE u.user_id=? AND c.id=? AND c.category=? AND c.active=1", (user_id, cosmetic_id, categories[slot]))).fetchone()
            if not row: raise HTTPException(403, "Cosmetic is not owned")
        await connection.execute("INSERT INTO user_loadout(user_id," + ",".join(slots) + ") VALUES (?" + ",?" * len(slots) + ") ON CONFLICT(user_id) DO UPDATE SET " + ",".join(f"{slot}=excluded.{slot}" for slot in slots), (user_id, *[values[s] for s in slots]))
        await connection.commit()
    except Exception:
        await connection.rollback(); raise
    finally: await connection.close()
    return {"loadout": values}

async def _all(sql, params=()):
    connection = await db.connect()
    try: return await (await connection.execute(sql, params)).fetchall()
    finally: await connection.close()

@router.get("/{discord_id}")
async def read_profile(discord_id: int, owner_id: int = Depends(discord_identity)):
    if discord_id != owner_id: raise HTTPException(403, "Profile access denied")
    profile = await get_profile_by_discord_id(discord_id)
    if profile is None: raise HTTPException(404, "Bishoply profile not found")
    return profile
