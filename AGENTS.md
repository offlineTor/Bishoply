# Repository Guidelines

## Project Structure & Module Organization

Bishoply is a Discord chess activity with a Python backend and a Vite frontend.
- `auth_server.py` initializes FastAPI, Discord authentication, and API routers; `bot.py` runs the Discord bot.
- `backend/api/` defines HTTP endpoints and request models; `backend/services/` implements game and profile logic; `backend/database/db.py` owns SQLite schema and persistence.
- `frontend/main.js`, `index.html`, and `style.css` contain the interface and styling. `frontend/dist/` contains generated build output.
- Root SQLite files hold local data. `logs/` and `pids/` contain runtime artifacts.

## Build, Test, and Development Commands

Run backend commands from the repository root because the database path is relative.
- `cd frontend && npm ci`: install frontend dependencies from the lockfile.
- `cd frontend && npm run dev`: start Vite on port 5173; `/api` and `/health` proxy to port 8000.
- `cd frontend && npm run build`: generate the production frontend in `dist/`.
- `source .venv/bin/activate` then `uvicorn auth_server:app --host 127.0.0.1 --port 8000`: run the API using the existing Python environment.
- `python3 bot.py`: run the bot with that environment activated.
- `./start.sh`: start available services, including a public tunnel when `cloudflared` is installed. Use `./status.sh`, `./logs.sh`, and `./stop.sh` to manage them.

## Coding Style & Naming Conventions

Follow surrounding code: four-space Python indentation, snake_case functions and modules, PascalCase request models, and uppercase constants. JavaScript uses two-space indentation, camelCase names, ES modules, double quotes, and semicolons. Keep HTTP handling in routers and business rules in services. No formatter or linter is configured.

## Testing Guidelines

No automated test framework, test command, or coverage threshold is configured. Build the frontend and smoke-test `/health` plus affected Discord activity flows. For game changes, check creation, joining, legal/illegal moves, resignation, and history. Use isolated SQLite data for write tests. Name future Python tests `test_*.py` and document their runner.

## Commit & Pull Request Guidelines

Git metadata is unavailable in this checkout, so existing commit conventions cannot be verified. Use concise imperative subjects. PRs should describe behavior changes, validation performed, related issues, and screenshots for UI changes; flag schema changes explicitly.

## Security & Configuration

Keep `.env` secrets private: `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `DISCORD_TOKEN` configure the services. Exclude credentials, local databases, logs, virtual environments, and PID files from contributions.
