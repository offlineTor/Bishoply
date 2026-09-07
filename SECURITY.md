# Bishoply security boundary

The frontend and Discord Activity are public, untrusted clients. Minification
and source-map removal only reduce casual readability; they do not make client
code secret. Secrets, authoritative game rules, ratings, SR, integrity checks,
and privileged operations stay on the backend.

## Configuration

Set `BISHOPLY_ENV=production` in production and provide secrets through the
process environment or a deployment secret manager. `.env`, `.env.*`, local
SQLite databases, logs, credentials, and private keys are excluded from source
control. Use `.env.example` as the placeholder template.

Production uses exact opt-in `BISHOPLY_ALLOWED_ORIGINS` values, generic error
responses, security headers, and request throttling. The health endpoint only
returns `{ "status": "ok" }`.

Before release, the deployment must set `BISHOPLY_ENV=production`, configure a
stable HTTPS origin, and complete the PostgreSQL adapter migration. The current
development runtime intentionally refuses to run against a PostgreSQL URL until
that adapter is complete. The in-memory limiter is suitable for one process;
multi-instance production requires a shared Redis/provider limiter.

## Authentication and authorization

Discord OAuth identity is verified server-side. Practice operations require a
private Practice key and ownership check. Multiplayer state is validated by the
backend before moves, results, ratings, or SR are changed. Client supplied
identifiers are requests, never proof of identity or ownership.

## Data minimization

Public responses should contain only fields required by the active client.
Engine internals, context snapshots, integrity details, credentials, and
database paths must not be serialized into launch responses.

## Incident response

If a credential is ever committed or exposed, revoke and rotate it immediately,
then audit access logs and remove the secret from repository history. Report
security issues privately to the Bishoply maintainers; a dedicated reporting
address will be added before public launch.
