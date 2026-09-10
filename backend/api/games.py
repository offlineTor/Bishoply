import chess

from fastapi import APIRouter, HTTPException, Query, Depends, Header, Request
from pydantic import BaseModel

from backend.services.game_service import (
    create_casual_game,
    get_game,
    join_casual_game,
    list_user_games,
    make_move,
    resign_game,
    create_private_game_for_user, join_private_game_for_user,
)
from backend.practice.auth import discord_identity
from backend import accounts
from backend.database.db import connect


router = APIRouter(
    prefix="/api/games",
    tags=["games"],
)

async def _generic_user(request: Request, authorization: str | None = Header(default=None)):
    if authorization:
        discord_id = await discord_identity(authorization)
        db = await connect()
        try: row = await (await db.execute("SELECT id FROM users WHERE discord_id=?", (discord_id,))).fetchone()
        finally: await db.close()
        if not row: raise HTTPException(404, "Bishoply profile not found")
        return row["id"]
    return await accounts.session_user(request)

@router.post("/private")
async def create_private(request: Request, user_id: int = Depends(_generic_user)):
    result = await create_private_game_for_user(user_id)
    if not result["ok"]: raise HTTPException(404, "Bishoply profile not found")
    return {"game_id": result["game"]["game_id"], "code": result["code"], "game": result["game"]}

@router.post("/private/{code}/join")
async def join_private(code: str, request: Request, user_id: int = Depends(_generic_user)):
    result = await join_private_game_for_user(code.upper(), user_id)
    if not result["ok"]:
        raise HTTPException(409 if result["error"] in {"game_full", "cannot_join_own_game"} else 404, result["error"])
    return result["game"]

@router.get("/private/{code}")
async def read_private(code: str, request: Request, user_id: int = Depends(_generic_user)):
    result = await get_game(code.upper())
    if not result["ok"]: raise HTTPException(404, "Game not found")
    game = result["game"]
    players = {str((game.get("white") or {}).get("id")), str((game.get("black") or {}).get("id"))}
    if str(user_id) not in players: raise HTTPException(403, "Game access denied")
    return game


def _match_response(game, owner_id):
    """Minimal matchmaking contract; full state is fetched from the authorized game route."""
    owner = str(owner_id)
    color = "white" if str((game.get("white") or {}).get("discord_id")) == owner else "black"
    opponent = game.get("black") if color == "white" else game.get("white")
    safe_opponent = None
    if opponent:
        safe_opponent = {key: opponent.get(key) for key in ("display_name", "username", "avatar_url", "chess_rating", "sr")}
    return {"status": game.get("status"), "game_id": game.get("game_id"),
            "assigned_color": color, "opponent": safe_opponent}


class CreateGameRequest(BaseModel):
    discord_id: int


class JoinGameRequest(BaseModel):
    discord_id: int


class MoveRequest(BaseModel):
    discord_id: int
    move: str


class ResignRequest(BaseModel):
    discord_id: int


@router.post("/casual")
async def create_game(
    payload: CreateGameRequest,
    owner_id: int = Depends(discord_identity),
):
    if payload.discord_id != owner_id:
        raise HTTPException(status_code=403, detail="Discord identity does not match the requested player")
    result = await create_casual_game(
        payload.discord_id
    )

    if not result["ok"]:
        handle_game_error(
            result["error"]
        )

    return _match_response(result["game"], owner_id)


@router.get("/history/{discord_id}")
async def read_user_game_history(
    discord_id: int,
    owner_id: int = Depends(discord_identity),
    limit: int = Query(
        default=25,
        ge=1,
        le=100,
    ),
    offset: int = Query(default=0, ge=0, le=100000),
):
    if discord_id != owner_id:
        raise HTTPException(status_code=403, detail="History access denied")
    result = await list_user_games(
        discord_id,
        limit,
        offset,
    )

    if not result["ok"]:
        handle_game_error(
            result["error"]
        )

    return {
        "discord_id": str(
            discord_id
        ),
        "games": result["games"],
    }


@router.post("/{game_id}/join")
async def join_game(
    game_id: str,
    payload: JoinGameRequest,
    owner_id: int = Depends(discord_identity),
):
    if payload.discord_id != owner_id:
        raise HTTPException(status_code=403, detail="Discord identity does not match the requested player")
    result = await join_casual_game(
        game_id,
        payload.discord_id,
    )

    if not result["ok"]:
        handle_game_error(
            result["error"]
        )

    return _match_response(result["game"], owner_id)


@router.get("/{game_id}")
async def read_game(
    game_id: str,
    owner_id: int = Depends(discord_identity),
):
    result = await get_game(
        game_id
    )

    if not result["ok"]:
        handle_game_error(
            result["error"]
        )

    game = result["game"]
    players = {str((game.get("white") or {}).get("discord_id")), str((game.get("black") or {}).get("discord_id"))}
    if str(owner_id) not in players:
        raise HTTPException(status_code=403, detail="Game access denied")
    return game


@router.get("/{game_id}/legal-moves")
async def read_legal_moves(
    game_id: str,
    discord_id: int,
    owner_id: int = Depends(discord_identity),
):
    if discord_id != owner_id:
        raise HTTPException(status_code=403, detail="Discord identity does not match the requested player")
    result = await get_game(
        game_id
    )

    if not result["ok"]:
        handle_game_error(
            result["error"]
        )

    game = result["game"]

    if game["status"] != "active":
        return {
            "game_id": game_id,
            "turn": game["turn"],
            "your_color": None,
            "can_move": False,
            "moves": [],
        }

    discord_id_string = str(
        discord_id
    )

    white_id = (
        str(
            game["white"]["discord_id"]
        )
        if game["white"]
        else None
    )

    black_id = (
        str(
            game["black"]["discord_id"]
        )
        if game["black"]
        else None
    )

    if (
        discord_id_string
        == white_id
    ):
        your_color = "white"

    elif (
        discord_id_string
        == black_id
    ):
        your_color = "black"

    else:
        raise HTTPException(
            status_code=403,
            detail="You are not a player in this game",
        )

    if your_color != game["turn"]:
        return {
            "game_id": game_id,
            "turn": game["turn"],
            "your_color": your_color,
            "can_move": False,
            "moves": [],
        }

    board = chess.Board(
        game["fen"]
    )

    moves = []

    for move in board.legal_moves:
        moves.append(
            {
                "uci": move.uci(),
                "from": chess.square_name(
                    move.from_square
                ),
                "to": chess.square_name(
                    move.to_square
                ),
                "promotion": (
                    chess.piece_name(
                        move.promotion
                    )
                    if move.promotion
                    else None
                ),
            }
        )

    return {
        "game_id": game_id,
        "turn": game["turn"],
        "your_color": your_color,
        "can_move": True,
        "moves": moves,
    }


@router.post("/{game_id}/move")
async def play_move(
    game_id: str,
    payload: MoveRequest,
    owner_id: int = Depends(discord_identity),
):
    if payload.discord_id != owner_id:
        raise HTTPException(status_code=403, detail="Discord identity does not match the requested player")
    result = await make_move(
        game_id,
        payload.discord_id,
        payload.move,
    )

    if not result["ok"]:
        handle_game_error(
            result["error"]
        )

    return result


@router.post("/{game_id}/resign")
async def resign(
    game_id: str,
    payload: ResignRequest,
    owner_id: int = Depends(discord_identity),
):
    if payload.discord_id != owner_id:
        raise HTTPException(status_code=403, detail="Discord identity does not match the requested player")
    result = await resign_game(
        game_id,
        payload.discord_id,
    )

    if not result["ok"]:
        handle_game_error(
            result["error"]
        )

    return result["game"]


def handle_game_error(
    error: str,
):
    if error == "user_not_found":
        raise HTTPException(
            status_code=404,
            detail="Bishoply user not found",
        )

    if error == "game_not_found":
        raise HTTPException(
            status_code=404,
            detail="Game not found",
        )

    if error == "cannot_join_own_game":
        raise HTTPException(
            status_code=400,
            detail="You cannot join your own game",
        )

    if error == "game_full":
        raise HTTPException(
            status_code=409,
            detail="This game already has two players",
        )

    if error == "game_not_joinable":
        raise HTTPException(
            status_code=409,
            detail="This game cannot be joined",
        )

    if error == "waiting_for_opponent":
        raise HTTPException(
            status_code=409,
            detail="Waiting for an opponent",
        )

    if error == "game_not_active":
        raise HTTPException(
            status_code=409,
            detail="This game is no longer active",
        )

    if error == "not_a_player":
        raise HTTPException(
            status_code=403,
            detail="You are not a player in this game",
        )

    if error == "not_your_turn":
        raise HTTPException(
            status_code=403,
            detail="It is not your turn",
        )

    if error == "invalid_uci":
        raise HTTPException(
            status_code=400,
            detail="Invalid move format",
        )

    if error == "illegal_move":
        raise HTTPException(
            status_code=400,
            detail="Illegal move",
        )

    raise HTTPException(
        status_code=400,
        detail=error,
    )
