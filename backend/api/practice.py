"""Practice routes never accept arbitrary FENs or mutate multiplayer games."""
from typing import Literal
import re
import logging
from fastapi import APIRouter, Header, Query, Depends, HTTPException, Request as HttpRequest
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.practice import config, service
from backend.analysis.service import get_review
from backend.practice.auth import discord_identity
from backend import accounts
from backend.database import db

router = APIRouter(prefix='/api/practice', tags=['unrated practice'])
log = logging.getLogger('uvicorn.error')


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CreateRequest(Request):
    discord_id: int | None = Field(default=None, gt=0)
    bot_id: str = Field(min_length=1,max_length=32)
    player_color: Literal['white','black'] = 'white'


class PositionRequest(Request):
    expected_ply: int = Field(ge=0,le=config.MAX_HISTORY_PLIES)


class MoveRequest(PositionRequest):
    move: str | None = Field(default=None, pattern=r'^[a-h][1-8][a-h][1-8][qrbn]?$')
    # Accept the historical browser field once, then normalize to `move`.
    # This prevents stale Activity bundles from producing an opaque 422 while
    # preserving one canonical service contract.
    uci: str | None = Field(default=None, pattern=r'^[a-h][1-8][a-h][1-8][qrbn]?$')
    expected_ply: int | None = Field(default=None, ge=0, le=config.MAX_HISTORY_PLIES)

    @model_validator(mode='after')
    def normalize_move(self):
        if self.move is None and self.uci is not None:
            self.move = self.uci
        if self.move is None:
            raise ValueError('move is required')
        return self


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


async def canonical_owner(request: HttpRequest, authorization: str | None = None):
    if authorization:
        discord_id = await discord_identity(authorization)
        connection = await db.connect()
        try:
            row = await (await connection.execute("SELECT id FROM users WHERE discord_id=?", (discord_id,))).fetchone()
            if row:
                return row['id'], discord_id
        finally:
            await connection.close()
        raise HTTPException(404, 'Bishoply user not found')
    return await accounts.session_user(request), None


async def authenticated_owner(request: HttpRequest, authorization: str | None = Header(None)):
    return await canonical_owner(request, authorization)


@router.get('/active')
async def active_game(request: HttpRequest, authorization: str | None = Header(None)):
    user_id, discord_id = await authenticated_owner(request, authorization)
    connection = await db.connect()
    try:
        await service.storage.cleanup_active_games(connection, user_id, discord_id)
        await connection.commit()
        rows = await (await connection.execute("""SELECT public_id FROM practice_games
            WHERE status='active' AND (owner_user_id=? OR (? IS NOT NULL AND owner_discord_id=?))
            ORDER BY created_at DESC, id DESC""", (user_id, discord_id, discord_id))).fetchall()
        if not rows:
            return {'active': False, 'game': None}
        # The access-key capability is intentionally bypassed only after the
        # canonical authenticated owner has been verified server-side.
        game = await service.get(rows[0]['public_id'], owner_user_id=user_id, owner_discord_id=discord_id)
        return {'active': True, 'game_id': rows[0]['public_id'], 'game': game}
    finally:
        await connection.close()


@router.get('/history')
async def practice_history(request: HttpRequest, authorization: str | None = Header(None), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)):
    user_id, discord_id = await canonical_owner(request, authorization)
    connection = await db.connect()
    try:
        rows = await (await connection.execute("""SELECT public_id,player_color,bot_id,status,result,termination_reason,ply,created_at,updated_at,completed_at
            FROM practice_games WHERE (owner_user_id=? OR (? IS NOT NULL AND owner_discord_id=?))
            ORDER BY created_at DESC LIMIT ? OFFSET ?""", (user_id, discord_id, discord_id, limit, offset))).fetchall()
        games = []
        for row in rows:
            status = row['status']
            player_color = row['player_color']
            if status == 'active':
                user_result = 'in_progress'
            elif row['termination_reason'] == 'superseded':
                user_result = 'abandoned'
            elif status == 'draw':
                user_result = 'draw'
            else:
                winner = 'white' if status == 'white_win' else 'black'
                user_result = 'win' if winner == player_color else 'loss'
            bot = config.BOTS.get(row['bot_id'])
            opponent = {'display_name': bot.display_name if bot else 'Bishoply Bot', 'username': bot.bot_id if bot else None}
            games.append({
                'game_id': row['public_id'], 'public_id': row['public_id'],
                'user_color': player_color, 'user_result': user_result,
                'status': status, 'result': row['result'],
                'termination_reason': row['termination_reason'],
                'move_count': row['ply'], 'ply': row['ply'],
                'created_at': row['created_at'], 'updated_at': row['updated_at'],
                'completed_at': row['completed_at'], 'competitive_decision': None,
                'opponent': opponent,
            })
        return {'games': games, 'limit': limit, 'offset': offset}
    finally:
        await connection.close()


@router.post('/games',status_code=201)
async def create_game(payload: CreateRequest, request: HttpRequest, authorization: str | None = Header(None)):
    owner_id = await practice_owner(request, authorization)
    if owner_id is not None:
        if payload.discord_id != owner_id:
            log.warning('practice_ownership_denied reason=discord_id_mismatch bot=%s', payload.bot_id)
            raise HTTPException(403,'Discord identity does not match the requested player')
        return await service.create(owner_id, payload.bot_id, payload.player_color)
    if payload.discord_id is not None:
        # A browser session is identified by its HttpOnly session cookie; a
        # client-supplied Discord id is never accepted as a substitute.
        log.warning('practice_ownership_denied reason=unauthenticated_payload bot=%s', payload.bot_id)
        raise HTTPException(422, 'Authenticate with Bishoply before creating Practice')
    user_id = await accounts.session_user(request)
    return await service.create(None, payload.bot_id, payload.player_color, user_id=user_id)


@router.get('/games/{game_id}')
async def read_game(game_id: str, request: HttpRequest, x_practice_key: str | None = Header(None), authorization: str | None = Header(None)):
    owner = await authenticated_owner(request, authorization) if not x_practice_key else (None, None)
    return await service.get(game_id,x_practice_key,*(owner or (None,None)))


@router.post('/games/{game_id}/move')
async def player_move(game_id: str, request: HttpRequest, x_practice_key: str | None = Header(None), authorization: str | None = Header(None)):
    stage = 'route_entered'
    log.info('practice_move_route_entered game=%s content_type=%s authorization=%s practice_key=%s',
             game_id, request.headers.get('content-type', ''), bool(authorization), bool(x_practice_key))
    try:
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(400, 'Practice move payload must be valid JSON') from exc
        if not isinstance(raw, dict):
            raise HTTPException(400, 'Practice move payload must be an object')
        log.info('practice_move_payload_received game=%s keys=%s types=%s',
                 game_id, sorted(raw.keys()), {key: type(value).__name__ for key, value in raw.items()})
        move = raw.get('move') or raw.get('uci')
        expected = raw.get('expected_ply')
        if not isinstance(move, str) or not re.fullmatch(r'[a-h][1-8][a-h][1-8][qrbn]?', move):
            raise HTTPException(422, 'Invalid Practice move payload')
        if expected is not None:
            try: expected = int(expected)
            except (TypeError, ValueError): raise HTTPException(422, 'Invalid Practice ply')
            if expected < 0: raise HTTPException(422, 'Invalid Practice ply')
        stage = 'payload_normalized'
        log.info('practice_move_payload_normalized game=%s move=%s expected_ply=%s source=%s', game_id, move, expected, 'move' if raw.get('move') else 'uci')
        owner = await authenticated_owner(request, authorization) if not x_practice_key else (None, None)
        log.info('practice_move_owner_resolved game=%s owner_user_id=%s legacy_discord=%s',
                 game_id, owner[0] if owner else None, bool(owner and owner[1]))
        stage = 'owner_resolved'
        result = await service.player_move(game_id, x_practice_key, move, expected, *(owner or (None, None)))
        log.info('practice_move_state_loaded game=%s ply=%s', game_id, result.get('ply'))
        return result
    except Exception as exc:
        log.error('practice_move_failure game=%s stage=%s type=%s reason=%s',
                  game_id, stage, type(exc).__name__, 'request_failed')
        raise


@router.post('/games/{game_id}/bot-move')
async def bot_move(game_id: str, payload: PositionRequest, request: HttpRequest, x_practice_key: str | None = Header(None), authorization: str | None = Header(None)):
    owner = await authenticated_owner(request, authorization) if not x_practice_key else (None, None)
    return await service.bot_response(game_id,x_practice_key,payload.expected_ply,*(owner or (None,None)))


@router.post('/games/{game_id}/hint')
async def hint(game_id: str, payload: HintRequest, x_practice_key: str = Header(...)):
    return await service.hint(game_id,x_practice_key,payload.expected_ply,payload.stage)


@router.post('/games/{game_id}/resign')
async def resign(game_id: str, request: HttpRequest, x_practice_key: str | None = Header(None), authorization: str | None = Header(None)):
    owner = await authenticated_owner(request, authorization) if not x_practice_key else (None, None)
    return await service.resign(game_id,x_practice_key,*(owner or (None,None)))


@router.post('/games/{game_id}/undo')
async def undo(game_id: str, request: HttpRequest, x_practice_key: str | None = Header(None), authorization: str | None = Header(None)):
    owner = await authenticated_owner(request, authorization) if not x_practice_key else (None, None)
    return await service.undo(game_id, x_practice_key,*(owner or (None,None)))


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
