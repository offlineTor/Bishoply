from fastapi import APIRouter, Depends, Query
from backend.practice.auth import discord_identity
from backend.database.db import connect
from backend.services.leaderboard import read

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("")
async def leaderboard(kind: str = Query("rating", pattern="^(rating|sr)$"), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), owner_id: int = Depends(discord_identity)):
    db = await connect()
    try:
        user = await (await db.execute("SELECT id FROM users WHERE discord_id=?", (owner_id,))).fetchone()
    finally:
        await db.close()
    return await read(kind, limit, offset, user["id"] if user else None)
