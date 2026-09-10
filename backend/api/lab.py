from fastapi import APIRouter, HTTPException, Request
from backend import accounts
from backend.services import lab

router = APIRouter(prefix="/api/lab", tags=["lab"])

@router.get("/positions")
async def positions(request: Request):
    return {"positions": await lab.list_for_user(await accounts.session_user(request))}

@router.post("/positions")
async def save_position(request: Request):
    user_id = await accounts.session_user(request); payload = await request.json()
    if not isinstance(payload, dict): raise HTTPException(422, "Position payload must be an object")
    return await lab.create(user_id, payload.get("name"), payload.get("fen"))

@router.delete("/positions/{position_id}")
async def remove_position(position_id: int, request: Request):
    return await lab.delete(await accounts.session_user(request), position_id)

@router.post("/analyze")
async def analyze_position(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict): raise HTTPException(422, "Position payload must be an object")
    return await lab.analyze(payload.get("fen"), payload.get("depth"))

@router.post("/bot-move")
async def lab_bot_move(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict): raise HTTPException(422, "Position payload must be an object")
    return await lab.bot_move(payload.get("fen"), payload.get("bot_id", "scout"))
