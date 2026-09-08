"""Practice routes never accept arbitrary FENs or mutate multiplayer games."""
from typing import Literal
from fastapi import APIRouter, Header, Query, Depends, HTTPException, Request as HttpRequest
from pydantic import BaseModel, ConfigDict, Field
from backend.practice import config, service
from backend.analysis.service import get_review
from backend.practice.auth import discord_identity
from backend import accounts

router = APIRouter(prefix='/api/practice', tags=['unrated practice'])


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CreateRequest(Request):
    discord_id: int | None = Field(default=None, gt=0)
    bot_id: str = Field(min_length=1,max_length=32)
    player_color: Literal['white','black'] = 'white'


class PositionRequest(Request):
    expected_ply: int = Field(ge=0,le=config.MAX_HISTORY_PLIES)


class MoveRequest(PositionRequest):
    move: str = Field(pattern=r'^[a-h][1-8][a-h][1-8][qrbn]?$')


class HintRequest(PositionRequest):
    stage: int = Field(ge=1,le=3)


async def practice_owner(request: HttpRequest, authorization: str | None = Header(None)):
    """Resolve Discord bearer identity or the canonical web session.

    The small dependency keeps the historical Discord dependency override used
    by the Practice test harness while allowing browser sessions to use the
    same route without a fabricated Discord id.
    """
    if authorization:
        return await discord_identity(authorization)
    override = request.app.dependency_overrides.get(discord_identity)
    if override is not None:
        value = override()
        return await value if hasattr(value, "__await__") else value
    return None


@router.get('/bots')
async def list_bots():
    return {'strength_label':config.LABEL,'calibration_version':config.VERSION,
            'bots':[bot.public() for bot in config.ROSTER]}


@router.post('/games',status_code=201)
async def create_game(payload: CreateRequest, request: HttpRequest, authorization: str | None = Header(None)):
    owner_id = await practice_owner(request, authorization)
    if owner_id is not None:
        if payload.discord_id != owner_id:
            raise HTTPException(403,'Discord identity does not match the requested player')
        return await service.create(owner_id, payload.bot_id, payload.player_color)
    if payload.discord_id is not None:
        # A browser session is identified by its HttpOnly session cookie; a
        # client-supplied Discord id is never accepted as a substitute.
        raise HTTPException(422, 'Authenticate with Bishoply before creating Practice')
    user_id = await accounts.session_user(request)
    return await service.create(None, payload.bot_id, payload.player_color, user_id=user_id)


@router.get('/games/{game_id}')
async def read_game(game_id: str, x_practice_key: str = Header(...)):
    return await service.get(game_id,x_practice_key)


@router.post('/games/{game_id}/move')
async def player_move(game_id: str, payload: MoveRequest, x_practice_key: str = Header(...)):
    return await service.player_move(game_id,x_practice_key,payload.move,payload.expected_ply)


@router.post('/games/{game_id}/bot-move')
async def bot_move(game_id: str, payload: PositionRequest, x_practice_key: str = Header(...)):
    return await service.bot_response(game_id,x_practice_key,payload.expected_ply)


@router.post('/games/{game_id}/hint')
async def hint(game_id: str, payload: HintRequest, x_practice_key: str = Header(...)):
    return await service.hint(game_id,x_practice_key,payload.expected_ply,payload.stage)


@router.post('/games/{game_id}/resign')
async def resign(game_id: str, x_practice_key: str = Header(...)):
    return await service.resign(game_id,x_practice_key)


@router.post('/games/{game_id}/undo')
async def undo(game_id: str, x_practice_key: str = Header(...)):
    return await service.undo(game_id, x_practice_key)


@router.get('/games/{game_id}/analysis/{ply}')
async def read_feedback(game_id: str, ply: int, x_practice_key: str = Header(...)):
    return await get_review(game_id,kind='feedback',ply=ply,key=x_practice_key)


@router.post('/games/{game_id}/analysis/{ply}')
async def request_feedback(game_id: str, ply: int, x_practice_key: str = Header(...)):
    return await get_review(game_id,True,kind='feedback',ply=ply,key=x_practice_key)


@router.get('/games/{game_id}/review')
async def read_review(game_id: str, x_practice_key: str = Header(...)):
    return await get_review(game_id,kind='practice',key=x_practice_key)


@router.post('/games/{game_id}/review')
async def request_review(game_id: str, new_revision: bool = Query(False), x_practice_key: str = Header(...)):
    return await get_review(game_id,True,kind='practice',key=x_practice_key,new_revision=new_revision)
