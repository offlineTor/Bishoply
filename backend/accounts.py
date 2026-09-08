"""Unified Bishoply accounts, provider identities, and web sessions."""
import base64, hashlib, hmac, json, os, secrets, time
from datetime import datetime, timedelta, timezone
import httpx
import logging
from fastapi import HTTPException, Request
from backend.database import db

PROVIDERS = {"discord", "google", "apple"}
log = logging.getLogger("uvicorn.error")

def _secret():
    value = os.getenv("SESSION_SECRET")
    if not value:
        raise HTTPException(503, "Web authentication is not configured")
    return value.encode()

def _hash(value): return hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()

def _state(provider, redirect_uri, user_id=None):
    payload = {"provider": provider, "redirect_uri": redirect_uri, "nonce": secrets.token_urlsafe(18), "exp": int(time.time()) + 600}
    if user_id is not None: payload["link_user_id"] = int(user_id)
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return raw + "." + hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()

def _verify_state(value, provider, redirect_uri):
    try:
        raw, sig = value.split(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()): raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if payload["provider"] != provider or payload["redirect_uri"] != redirect_uri or payload["exp"] < int(time.time()): raise ValueError
        return payload
    except Exception as exc:
        raise HTTPException(400, "Invalid or expired authentication state") from exc

def redirect_for(provider):
    default = "https://bishoply.onrender.com" if os.getenv("BISHOPLY_ENV", "development").lower() == "production" else "http://localhost:8000"
    base = os.getenv("BISHOPLY_API_ORIGIN", default).rstrip("/")
    return f"{base}/api/auth/{provider}/callback"

def configured(provider):
    if provider == "google": return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
    if provider == "apple": return bool(os.getenv("APPLE_CLIENT_ID") and os.getenv("APPLE_TEAM_ID") and os.getenv("APPLE_KEY_ID") and os.getenv("APPLE_PRIVATE_KEY"))
    return bool(os.getenv("DISCORD_CLIENT_ID") and os.getenv("DISCORD_CLIENT_SECRET"))

async def start(provider, user_id=None):
    if provider not in PROVIDERS: raise HTTPException(404, "Provider unavailable")
    if not configured(provider):
        log.warning("oauth_provider_unconfigured provider=%s", provider)
        raise HTTPException(503, f"{provider.title()} sign-in is not configured")
    redirect_uri = redirect_for(provider); state = _state(provider, redirect_uri, user_id)
    if provider == "google":
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + httpx.QueryParams({"client_id":os.getenv("GOOGLE_CLIENT_ID"),"redirect_uri":redirect_uri,"response_type":"code","scope":"openid profile email","state":state,"nonce":json.loads(base64.urlsafe_b64decode(state.split('.')[0]+'=='))['nonce']})
    elif provider == "discord":
        url = "https://discord.com/oauth2/authorize?" + httpx.QueryParams({"client_id":os.getenv("DISCORD_CLIENT_ID"),"redirect_uri":redirect_uri,"response_type":"code","scope":"identify","state":state})
    else:
        url = "https://appleid.apple.com/auth/authorize?" + httpx.QueryParams({"client_id":os.getenv("APPLE_CLIENT_ID"),"redirect_uri":redirect_uri,"response_type":"code","scope":"name email","state":state,"response_mode":"query"})
    return {"provider": provider, "authorization_url": str(url)}

async def exchange(provider, code, redirect_uri):
    if provider == "google":
        endpoint, data = "https://oauth2.googleapis.com/token", {"client_id":os.getenv("GOOGLE_CLIENT_ID"),"client_secret":os.getenv("GOOGLE_CLIENT_SECRET"),"code":code,"redirect_uri":redirect_uri,"grant_type":"authorization_code"}
    elif provider == "discord":
        endpoint, data = "https://discord.com/api/oauth2/token", {"client_id":os.getenv("DISCORD_CLIENT_ID"),"client_secret":os.getenv("DISCORD_CLIENT_SECRET"),"code":code,"redirect_uri":redirect_uri,"grant_type":"authorization_code"}
    else:
        raise HTTPException(503, "Apple sign-in requires configured server credentials")
    async with httpx.AsyncClient(timeout=8) as client:
        token = await client.post(endpoint, data=data)
        if token.status_code != 200: raise HTTPException(400, "Provider authorization failed")
        payload = token.json(); access = payload.get("access_token")
        if not access: raise HTTPException(400, "Provider authorization response was invalid")
        info_url = "https://openidconnect.googleapis.com/v1/userinfo" if provider == "google" else "https://discord.com/api/users/@me"
        info = await client.get(info_url, headers={"Authorization": f"Bearer {access}"})
        if info.status_code != 200: raise HTTPException(400, "Provider identity lookup failed")
        identity = info.json()
    subject = str(identity.get("sub") or identity.get("id") or "")
    if not subject: raise HTTPException(400, "Provider identity response was invalid")
    return subject, identity

async def resolve(provider, subject, metadata):
    connection = await db.connect()
    try:
        row = await (await connection.execute("SELECT user_id FROM auth_identities WHERE provider=? AND subject=?", (provider, subject))).fetchone()
        if row:
            user_id = row["user_id"]
            await connection.execute("UPDATE auth_identities SET last_login_at=CURRENT_TIMESTAMP,provider_metadata=? WHERE provider=? AND subject=?", (json.dumps(metadata), provider, subject))
        else:
            name = metadata.get("username") or metadata.get("name") or "Bishoply player"
            discord_id = int(subject) if provider == "discord" else None
            existing_user = None
            if discord_id is not None:
                existing_user = await (await connection.execute("SELECT id FROM users WHERE discord_id=?", (discord_id,))).fetchone()
            if existing_user:
                user_id = existing_user["id"]
            else:
                inserted = await (await connection.execute("INSERT INTO users(discord_id,username,display_name,avatar_url) VALUES (?,?,?,?) RETURNING id", (discord_id, name, metadata.get("global_name") or name, metadata.get("picture")))).fetchone()
                if not inserted:
                    raise RuntimeError("Account creation did not return an id")
                user_id = inserted["id"]
                await connection.execute("UPDATE users SET username_normalized=NULL, username_selected_at=NULL WHERE id=?", (user_id,))
            await connection.execute("INSERT INTO auth_identities(user_id,provider,subject,provider_metadata) VALUES (?,?,?,?)", (user_id, provider, subject, json.dumps(metadata)))
        await connection.commit(); return user_id
    except Exception:
        await connection.rollback(); raise
    finally: await connection.close()

async def create_session(user_id):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    connection = await db.connect()
    try:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).replace(tzinfo=None).isoformat(sep=" ")
        await connection.execute("INSERT INTO web_sessions(user_id,token_hash,csrf_hash,expires_at) VALUES (?,?,?,?)", (user_id, _hash(token), _hash(csrf), expires_at))
        await connection.commit()
    finally: await connection.close()
    return token, csrf

async def session_user(request: Request):
    token = request.cookies.get("bishoply_session")
    if not token: raise HTTPException(401, "Authentication required")
    connection = await db.connect()
    try:
        row = await (await connection.execute("SELECT user_id FROM web_sessions WHERE token_hash=? AND revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP", (_hash(token),))).fetchone()
        if not row: raise HTTPException(401, "Authentication required")
        return row["user_id"]
    finally: await connection.close()
