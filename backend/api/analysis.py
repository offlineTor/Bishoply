import os
from fastapi import APIRouter, Query, Header, HTTPException
from backend.analysis.service import get_review
from backend.practice.auth import discord_identity
from backend.services.game_service import get_game
router = APIRouter(prefix='/api/games', tags=['post-game review'])

async def _authorized_game(game_id, authorization):
    result = await get_game(game_id)
    if not result.get('ok'):
        raise HTTPException(404, 'Game not found')
    if os.getenv('BISHOPLY_ENV', 'development').lower() != 'production':
        return
    if not authorization:
        raise HTTPException(401, 'Discord authentication required')
    owner = await discord_identity(authorization)
    game = result['game']
    players = {str((game.get('white') or {}).get('discord_id')), str((game.get('black') or {}).get('discord_id'))}
    if str(owner) not in players:
        raise HTTPException(403, 'Game access denied')


@router.get('/{game_id}/analysis')
async def read_analysis(game_id: str, authorization: str | None = Header(default=None)):
    await _authorized_game(game_id, authorization)
    return await get_review(game_id)


@router.post('/{game_id}/analysis')
async def start_analysis(game_id: str, new_revision: bool = Query(False), authorization: str | None = Header(default=None)):
    await _authorized_game(game_id, authorization)
    return await get_review(game_id, enqueue=True, new_revision=new_revision)
