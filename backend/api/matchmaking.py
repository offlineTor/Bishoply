from fastapi import APIRouter, Depends, Header, HTTPException, Request

from backend.practice.auth import discord_identity
from backend.services import matchmaking
from backend.services.competitive import ensure_player
from backend import accounts
from backend.database.db import connect

router = APIRouter(prefix="/api/matchmaking/duel", tags=["matchmaking"])


async def competitive_identity(request: Request, authorization: str | None = Header(default=None)):
    """Resolve either a native Web session or Discord bearer to a player."""
    if authorization:
        discord_id = await discord_identity(authorization)
        db = await connect()
        try:
            row = await (await db.execute("SELECT id FROM users WHERE discord_id=?", (discord_id,))).fetchone()
        finally:
            await db.close()
        if not row: raise HTTPException(404, "Bishoply profile not found")
        return await ensure_player("discord", str(discord_id), row["id"])
    user_id = await accounts.session_user(request)
    return await ensure_player("web", str(user_id), user_id)


@router.post("/generic/join")
async def generic_join(player_id: int = Depends(competitive_identity)):
    return await matchmaking.join_generic(player_id)


@router.get("/generic/status")
async def generic_status(player_id: int = Depends(competitive_identity)):
    return await matchmaking.status_generic(player_id)


@router.post("/generic/cancel")
async def generic_cancel(player_id: int = Depends(competitive_identity)):
    return await matchmaking.cancel_generic(player_id)


@router.post("/join")
async def join(owner_id: int = Depends(discord_identity)):
    return await matchmaking.join(owner_id)


@router.get("/status")
async def status(owner_id: int = Depends(discord_identity)):
    return await matchmaking.status(owner_id)


@router.post("/cancel")
async def cancel(owner_id: int = Depends(discord_identity)):
    return await matchmaking.cancel(owner_id)
