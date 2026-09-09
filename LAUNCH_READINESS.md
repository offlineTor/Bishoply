# Bishoply launch readiness

## Shared architecture

The web client and Discord Activity use the same FastAPI service, PostgreSQL
database, canonical account IDs, Practice service, Bot Engine, multiplayer
service, ratings, SR, history, and cosmetics storage.

## Builds

```bash
VITE_RUNTIME=web VITE_API_BASE_URL=https://bishoply.onrender.com npm run build:web
VITE_RUNTIME=discord VITE_API_PROXY_BASE=/api npm run build:discord
```

The web client uses direct HTTPS API requests with the Bishoply session cookie.
The Activity client uses relative proxy requests and an in-memory Discord bearer
token. The Activity transport rejects absolute backend URLs.

## Render configuration

Backend: Render Web Service, Docker runtime, `uvicorn auth_server:app --host
0.0.0.0 --port $PORT`, with PostgreSQL, Redis, Stockfish, Discord, and session
secrets configured server-side.

Public web: Render Static Site publishing `frontend/dist`, built with
`VITE_RUNTIME=web` and `VITE_API_BASE_URL=https://bishoply.onrender.com`.

Discord Activity: a separate Render Static Site publishing `frontend/dist`,
built with `VITE_RUNTIME=discord` and `VITE_API_PROXY_BASE=/api`.

The exact Activity static-site hostname must be copied from Render into the
Discord Developer Portal. Root `/` maps to that Activity site; `/api` maps to
`https://bishoply.onrender.com`.

## Required live checks

Run the web and Activity smoke tests separately: authenticate, load profile,
create Practice as White and Black, make a move, verify a legal bot reply and
history, refresh and recover the active game, then test Duel and result
settlement. Treat `/api/auth/session` returning 401 before login as signed out.
