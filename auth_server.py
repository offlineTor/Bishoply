import os
import time
import uuid
import logging

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.api.practice import router as practice_router
from backend.practice.storage import initialize as initialize_practice
from backend.api.analysis import router as analysis_router
from backend.analysis.service import initialize as initialize_analysis
from backend.api.games import router as games_router
from backend.api.profile import router as profile_router
from backend.api.voice import router as voice_router
from backend.api.matchmaking import router as matchmaking_router
from backend.services import matchmaking
from backend.api.leaderboard import router as leaderboard_router
from backend.api.accounts import router as accounts_router
from backend.database.db import (
    connect,
    get_or_create_user,
    initialize_database,
    migrate_discord_id_columns,
    migrate_practice_identity_columns,
)
from backend.security import SharedRateLimiter, client_key, is_production


load_dotenv()

ENVIRONMENT = os.getenv("BISHOPLY_ENV", "development").strip().lower()
startup_log = logging.getLogger("uvicorn.error")

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")

if not CLIENT_ID:
    raise RuntimeError(
        "DISCORD_CLIENT_ID is missing from .env"
    )

if not CLIENT_SECRET:
    raise RuntimeError(
        "DISCORD_CLIENT_SECRET is missing from .env"
    )

if ENVIRONMENT == "production":
    required = {
        "DATABASE_URL": os.getenv("DATABASE_URL"),
        "BISHOPLY_ALLOWED_ORIGINS": os.getenv("BISHOPLY_ALLOWED_ORIGINS"),
        "BISHOPLY_FRONTEND_ORIGIN": os.getenv("BISHOPLY_FRONTEND_ORIGIN"),
        "DISCORD_BOT_TOKEN": os.getenv("DISCORD_BOT_TOKEN"),
        "SESSION_SECRET": os.getenv("SESSION_SECRET"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing required production configuration: " + ", ".join(missing))
    if "*" in required["BISHOPLY_ALLOWED_ORIGINS"]:
        raise RuntimeError("BISHOPLY_ALLOWED_ORIGINS cannot contain wildcard origins")
    if not required["BISHOPLY_FRONTEND_ORIGIN"].startswith("https://"):
        raise RuntimeError("BISHOPLY_FRONTEND_ORIGIN must use HTTPS in production")
    if os.getenv("BISHOPLY_MULTI_INSTANCE", "false").lower() == "true" and not os.getenv("REDIS_URL"):
        raise RuntimeError("REDIS_URL is required for multi-instance production")


app = FastAPI(
    title="Bishoply API",
    version="1.0.0",
)

configured_origins = os.getenv("BISHOPLY_ALLOWED_ORIGINS")
origin_default = "" if is_production() else "http://localhost:5173,http://127.0.0.1:5173"
allowed_origins = [origin.strip() for origin in (configured_origins or origin_default).split(",")
                   if origin.strip() and origin.strip() != "*"]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins,
                   allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Practice-Key", "X-CSRF-Token"])

_limiter = SharedRateLimiter()


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    sensitive_queue = "/queue" in request.url.path
    if ((request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"))
            or sensitive_queue):
        if not await _limiter.allow(client_key(request)):
            return JSONResponse(status_code=429, headers={"Retry-After": "5"}, content={"error": "rate_limited", "message": "Too many requests. Please try again shortly."})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    tunnel_origin = "" if is_production() else " https://*.trycloudflare.com"
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; connect-src 'self' https://bishoply.onrender.com https://discord.com https://*.discordsays.com" + tunnel_origin + "; img-src 'self' data: https://cdn.discordapp.com; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' https://*.discordsays.com; frame-ancestors https://*.discordsays.com https://discord.com")
    if is_production():
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    import logging
    logging.getLogger("bishoply.http").info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    logging.getLogger("bishoply.api").warning(
        "request_validation_failed path=%s fields=%s",
        request.url.path,
        [".".join(str(part) for part in error.get("loc", ())) for error in exc.errors()],
    )
    return JSONResponse(status_code=422, content={"error": "invalid_request", "message": "The request could not be validated."})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # Detailed exceptions remain in server logging configuration, never in API
    # responses. Avoid logging request headers or body here.
    import logging
    logging.getLogger("bishoply.api").exception("Unhandled API error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Something went wrong. Please try again."})


app.include_router(
    profile_router
)

app.include_router(analysis_router)
app.include_router(practice_router)

app.include_router(
    games_router
)
app.include_router(voice_router)
app.include_router(matchmaking_router)
app.include_router(leaderboard_router)
app.include_router(accounts_router)


class ExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=2048)


@app.on_event("startup")
async def startup():
    startup_log.info("Bishoply production startup: environment=%s", ENVIRONMENT)
    startup_log.info("Discord bot token configured: %s", "yes" if os.getenv("DISCORD_BOT_TOKEN") else "no")
    startup_log.info("Bishoply database schema init start")
    await initialize_database()
    startup_log.info("Bishoply database schema init complete")
    startup_log.info("Bishoply practice init start")
    await initialize_practice()
    startup_log.info("Bishoply practice init complete")
    startup_log.info("Bishoply analysis init start")
    await initialize_analysis()
    startup_log.info("Bishoply analysis init complete")
    startup_log.info("Bishoply matchmaking init start")
    await matchmaking.initialize()
    startup_log.info("Bishoply matchmaking init complete")
    startup_log.info("Bishoply Discord ID migration start")
    db = await connect()
    try:
        await migrate_discord_id_columns(db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    startup_log.info("Bishoply Discord ID migration complete")
    startup_log.info("Bishoply Practice identity migration start")
    db = await connect()
    try:
        await migrate_practice_identity_columns(db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    startup_log.info("Bishoply Practice identity migration complete")
    if ENVIRONMENT == "production" or os.getenv("BISHOPLY_BOT_IN_APP", "false").lower() == "true":
        from bot import start_bot
        startup_log.info("Calling Bishoply Discord start_bot()")
        await start_bot()


@app.on_event("shutdown")
async def shutdown():
    # Practice's reusable Stockfish pool is independent from rated Duel and
    # must be closed with the FastAPI process to avoid orphan engines.
    from backend.practice.bots import close_pool
    await close_pool()
    if ENVIRONMENT == "production" or os.getenv("BISHOPLY_BOT_IN_APP", "false").lower() == "true":
        from bot import stop_bot
        await stop_bot()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness(request: Request):
    token = os.getenv("BISHOPLY_READINESS_TOKEN")
    if is_production() and (not token or request.headers.get("X-Readiness-Token") != token):
        raise HTTPException(status_code=404, detail="Not found")
    from backend.database.db import connect
    db = await connect()
    try:
        await db.execute("SELECT 1")
    finally:
        await db.close()
    return {"status": "ready"}


@app.post("/api/auth/discord")
async def exchange_discord_code(
    payload: ExchangeRequest,
):
    token_url = (
        "https://discord.com/api/oauth2/token"
    )

    form_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": payload.code,
    }

    headers = {
        "Content-Type":
            "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            token_url,
            data=form_data,
            headers=headers,
        )

    if token_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail="Discord token exchange failed",
        )

    token_data = token_response.json()

    access_token = (
        token_data["access_token"]
    )

    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            "https://discord.com/api/users/@me",
            headers={
                "Authorization":
                    f"Bearer {access_token}",
            },
        )

    if user_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail="Discord user lookup failed",
        )

    discord_user = (
        user_response.json()
    )

    discord_id = int(
        discord_user["id"]
    )

    username = (
        discord_user["username"]
    )

    display_name = (
        discord_user.get("global_name")
        or username
    )

    avatar_hash = (
        discord_user.get("avatar")
    )

    avatar_url = None

    if avatar_hash:
        avatar_url = (
            "https://cdn.discordapp.com/"
            f"avatars/{discord_id}/"
            f"{avatar_hash}.png"
        )

    await get_or_create_user(
        discord_id=discord_id,
        username=username,
        display_name=display_name,
        avatar_url=avatar_url,
    )
    # Keep Activity Discord auth linked to the canonical account identity.
    from backend.accounts import resolve as resolve_account_identity
    await resolve_account_identity("discord", str(discord_id), discord_user)

    return {
        "access_token": access_token,
        "token_type":
            token_data.get(
                "token_type",
                "Bearer",
            ),
        "expires_in":
            token_data.get(
                "expires_in"
            ),
        "scope":
            token_data.get(
                "scope"
            ),
        "user": {
            "id": str(
                discord_id
            ),
            "username":
                username,
            "display_name":
                display_name,
            "avatar_url":
                avatar_url,
        },
    }
