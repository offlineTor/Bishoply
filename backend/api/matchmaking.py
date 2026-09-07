from fastapi import APIRouter, Depends

from backend.practice.auth import discord_identity
from backend.services import matchmaking

router = APIRouter(prefix="/api/matchmaking/duel", tags=["matchmaking"])


@router.post("/join")
async def join(owner_id: int = Depends(discord_identity)):
    return await matchmaking.join(owner_id)


@router.get("/status")
async def status(owner_id: int = Depends(discord_identity)):
    return await matchmaking.status(owner_id)


@router.post("/cancel")
async def cancel(owner_id: int = Depends(discord_identity)):
    return await matchmaking.cancel(owner_id)
