# Bishoply production stabilization

The backend is shared by both clients. The web build uses `VITE_RUNTIME=web`
and `VITE_API_BASE_URL=https://bishoply.onrender.com`. The Activity build uses
`VITE_RUNTIME=discord` and `VITE_API_PROXY_BASE=/api`; it never uses the direct
API origin. Build with `npm run build:web` and `npm run build:discord`.

Render static web and Activity sites should publish `frontend/dist` from the
respective build. The API service runs `uvicorn auth_server:app --host
0.0.0.0 --port $PORT`. Discord Activity mappings keep the root frontend origin
and `/api` proxy to the backend. Practice, profile, history, and account data
remain server-authoritative and shared.

Before release, validate both deployments inside Discord and in a standalone
browser: authenticate, create Practice as White and Black, submit a move,
confirm a legal bot reply and persisted history, refresh and recover the active
game, then finish and verify the result. Inspect Render logs for the
`practice_*` lifecycle stages if a reply fails.
