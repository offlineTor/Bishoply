# Bishoply production deployment

## Current architecture audit

The backend keeps one service API for both SQLite and PostgreSQL. Development
uses `aiosqlite`; production uses the psycopg async/sync adapters selected from
`DATABASE_URL`. SQLite query idioms are translated by the compatibility layer,
and schema version 1 is recorded in `schema_migrations`.

Development remains SQLite. PostgreSQL runtime support is a required migration
step before production traffic; do not point the current process at a Postgres
URL and assume compatibility.

## Safe migration path

1. Provision a managed PostgreSQL database with TLS and daily backups.
2. Install `psycopg[binary]` in a staging environment.
3. Run `scripts/migrate_sqlite_to_postgres.py --sqlite bishoply.db` for a dry run.
4. Take a database backup and run the importer with `--apply --database-url ...`.
5. Validate row counts, foreign-key relationships, ratings, SR, games, moves,
   Practice state, analysis revisions, and matchmaking rows.
6. Run PostgreSQL integration and concurrency tests in staging. Matchmaking
   transactions use PostgreSQL row locking; the application never falls back to
   SQLite when `BISHOPLY_ENV=production`.
7. Configure Redis for shared production rate limiting, then deploy the backend.
8. Serve only `frontend/dist` from a static HTTPS host and set its API origin.
9. Configure Discord Activity URL mappings to the stable frontend domain.
10. Enable production traffic only after health, auth, Duel, Practice, Profile,
    History, and Leaderboard smoke tests pass.

The importer is non-destructive and rolls back the PostgreSQL transaction on any
row failure. It does not delete or rewrite the SQLite source.

## Process topology

Run FastAPI behind a trusted HTTPS reverse proxy. Run analysis workers as a
separate managed process only when launch features require them. Stockfish must
be installed server-side and configured by environment. Do not use a
trycloudflare URL for production.

Required production settings include `BISHOPLY_ENV=production`,
`DATABASE_URL`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
`BISHOPLY_ALLOWED_ORIGINS`, `BISHOPLY_FRONTEND_ORIGIN`, and
`VITE_API_BASE_URL` (an HTTPS API origin). Set `REDIS_URL` when running more
than one backend instance and `BISHOPLY_READINESS_TOKEN` for protected
readiness checks. No `.env` file should be uploaded to the host.

The public health check is `GET /health` and returns only `{ "status": "ok" }`.
`GET /ready` is provider-only in production and requires the readiness token;
it verifies a database connection without revealing infrastructure details.

## Backups and rollback

Use provider-managed daily backups with point-in-time recovery where available;
retain at least 30 days. Restore into a separate staging database, validate
counts and a sample of settled transactions, then switch the application only
after verification. Roll back frontend/backend releases independently. Never
roll back an irreversible schema migration without restoring a compatible
database backup.
