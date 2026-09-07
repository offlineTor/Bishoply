from fastapi import APIRouter, HTTPException, Depends

from backend.services.profile_service import (
    get_profile_by_discord_id,
)
from backend.practice.auth import discord_identity


router = APIRouter(
    prefix="/api/profile",
    tags=["profile"],
)


@router.get("/{discord_id}")
async def read_profile(
    discord_id: int,
    owner_id: int = Depends(discord_identity),
):
    if discord_id != owner_id:
        raise HTTPException(status_code=403, detail="Profile access denied")
    profile = await get_profile_by_discord_id(
        discord_id
    )

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="Bishoply profile not found",
        )

    return profile
