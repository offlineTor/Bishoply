import json
import os
import hmac
from fastapi import APIRouter, Request, Response, Query, HTTPException, Header
from pydantic import BaseModel
from backend import accounts
from backend.services.profile_service import get_profile_by_discord_id
from backend.database import db

router = APIRouter(prefix="/api/auth", tags=["authentication"])

class WebSignup(BaseModel):
    username: str
    email: str
    password: str
    confirm_password: str

class WebLogin(BaseModel):
    identifier: str
    password: str

class PasswordResetRequest(BaseModel):
    email: str

class PasswordResetConfirm(BaseModel):
    token: str
    password: str

async def _set_session(response, user_id):
    token, csrf = await accounts.create_session(user_id)
    secure = os.getenv("BISHOPLY_ENV", "development").lower() == "production"
    response.set_cookie("bishoply_session", token, httponly=True, secure=secure, samesite="lax", max_age=30 * 86400, path="/")
    response.set_cookie("bishoply_csrf", csrf, httponly=False, secure=secure, samesite="lax", max_age=30 * 86400, path="/")

@router.post("/signup")
async def web_signup(payload: WebSignup, response: Response):
    if payload.password != payload.confirm_password:
        raise HTTPException(422, "Passwords do not match")
    user_id = await accounts.create_web_account(payload.username, payload.email, payload.password)
    await _set_session(response, user_id)
    return {"authenticated": True, "user_id": user_id}

@router.post("/login")
async def web_login(payload: WebLogin, response: Response):
    user_id = await accounts.authenticate_web_account(payload.identifier, payload.password)
    await _set_session(response, user_id)
    return {"authenticated": True, "user_id": user_id}

@router.post("/forgot-password")
async def forgot_password(payload: PasswordResetRequest):
    if not os.getenv("BISHOPLY_EMAIL_PROVIDER"):
        raise HTTPException(503, "Password recovery is temporarily unavailable")
    await accounts.issue_password_reset(payload.email)
    return {"accepted": True, "message": "If that account exists, recovery instructions will be sent."}

@router.post("/reset-password")
async def reset_password(payload: PasswordResetConfirm):
    await accounts.reset_web_password(payload.token, payload.password)
    return {"reset": True}

@router.get("/{provider}/start")
async def auth_start(provider: str):
    return await accounts.start(provider)

@router.get("/{provider}/callback")
async def auth_callback(provider: str, code: str = Query(...), state: str = Query(...)):
    redirect_uri = accounts.redirect_for(provider)
    state_payload = accounts._verify_state(state, provider, redirect_uri)
    subject, metadata = await accounts.exchange(provider, code, redirect_uri)
    if state_payload.get("link_user_id"):
        connection = await db.connect()
        try:
            existing = await (await connection.execute("SELECT user_id FROM auth_identities WHERE provider=? AND subject=?", (provider, subject))).fetchone()
            if existing and int(existing["user_id"]) != int(state_payload["link_user_id"]):
                raise HTTPException(409, "That provider is already linked to another Bishoply account")
            if not existing:
                await connection.execute("INSERT INTO auth_identities(user_id,provider,subject,provider_metadata) VALUES (?,?,?,?)", (int(state_payload["link_user_id"]), provider, subject, json.dumps(metadata))); await connection.commit()
            user_id = int(state_payload["link_user_id"])
        finally: await connection.close()
    else:
        user_id = await accounts.resolve(provider, subject, metadata)
    token, csrf = await accounts.create_session(user_id)
    response = Response(status_code=302, headers={"Location": "/"})
    secure = os.getenv("BISHOPLY_ENV", "development").lower() == "production"
    response.set_cookie("bishoply_session", token, httponly=True, secure=secure, samesite="lax", max_age=30*86400, path="/")
    response.set_cookie("bishoply_csrf", csrf, httponly=False, secure=secure, samesite="lax", max_age=30*86400, path="/")
    return response

@router.get("/session")
async def current_session(request: Request):
    user_id = await accounts.session_user(request)
    connection = await db.connect()
    try:
        row = await (await connection.execute("SELECT discord_id FROM users WHERE id=?", (user_id,))).fetchone()
        if not row:
            return {"authenticated": True, "user_id": user_id, "profile": None}
        if row["discord_id"] is None:
            user = await (await connection.execute("SELECT username,display_name,avatar_url,created_at,username_selected_at FROM users WHERE id=?", (user_id,))).fetchone()
            rating = await (await connection.execute("SELECT rating,wins,losses,draws,rated_games FROM skill_ratings WHERE user_id=? AND pool='standard'", (user_id,))).fetchone()
            progression = await (await connection.execute("SELECT sr FROM progression WHERE user_id=?", (user_id,))).fetchone()
            profile = {"user_id": user_id, "username": user["username"], "username_selected": bool(user["username_selected_at"]), "display_name": user["display_name"], "avatar_url": user["avatar_url"], "discord_id": None,
                       "rating": round(float(rating["rating"])) if rating else 1200, "sr": int(progression["sr"]) if progression else 2500,
                       "wins": int(rating["wins"]) if rating else 0, "losses": int(rating["losses"]) if rating else 0,
                       "draws": int(rating["draws"]) if rating else 0, "games_played": int(rating["rated_games"]) if rating else 0,
                       "account_created_at": user["created_at"]}
            return {"authenticated": True, "user_id": user_id, "profile": profile}
    finally:
        await connection.close()
    profile = await get_profile_by_discord_id(int(row["discord_id"]))
    return {"authenticated": True, "user_id": user_id, "profile": profile}

@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("bishoply_session")
    csrf_cookie = request.cookies.get("bishoply_csrf")
    csrf_header = request.headers.get("X-CSRF-Token")
    if token and (not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header)):
        raise HTTPException(403, "CSRF validation failed")
    if token:
        connection = await db.connect()
        try:
            await connection.execute("UPDATE web_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash=?", (accounts._hash(token),)); await connection.commit()
        finally: await connection.close()
    response.delete_cookie("bishoply_session", path="/"); response.delete_cookie("bishoply_csrf", path="/")
    return {"authenticated": False}

@router.get("/connections")
async def connections(request: Request, authorization: str | None = Header(None)):
    if authorization and authorization.lower().startswith("bearer "):
        from backend.practice.auth import discord_identity
        discord_id = await discord_identity(authorization)
        row = await accounts.db.connect()
        try:
            user = await (await row.execute("SELECT id FROM users WHERE discord_id=?", (discord_id,))).fetchone()
        finally: await row.close()
        if not user: raise HTTPException(404, "Bishoply profile not found")
        user_id = user["id"]
    else:
        user_id = await accounts.session_user(request)
    connection = await db.connect()
    try:
        rows = await (await connection.execute("SELECT provider,created_at,last_login_at FROM auth_identities WHERE user_id=? ORDER BY provider", (user_id,))).fetchall()
        return {"connections": [{"provider": row["provider"], "connected": True, "created_at": row["created_at"], "last_login_at": row["last_login_at"]} for row in rows]}
    finally: await connection.close()

@router.get("/{provider}/link/start")
async def link_start(provider: str, request: Request):
    # Authentication is required before a provider-link flow can begin. The
    # callback still performs fresh provider verification and unique-identity
    # enforcement; no email-based account merges are performed.
    user_id = await accounts.session_user(request)
    return await accounts.start(provider, user_id)
