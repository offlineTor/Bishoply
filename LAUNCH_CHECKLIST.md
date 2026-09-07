# Bishoply launch checklist

## Staging validation (2026-09-07)

Provider-backed staging was **NOT TESTED**: no PostgreSQL, Redis, stable HTTPS
domains, Discord staging credentials, or hosting provider access is configured
in this environment. Local automated checks are recorded separately below.

- [NOT TESTED] Real PostgreSQL migration and functional flow
- [NOT TESTED] PostgreSQL matchmaking concurrency
- [NOT TESTED] Redis shared limiter across two instances
- [NOT TESTED] Redis outage fail-closed behavior
- [NOT TESTED] Stable HTTPS frontend/API
- [NOT TESTED] Discord Activity staging authentication
- [NOT TESTED] Two-account Duel smoke test
- [NOT TESTED] Provider backups/PITR
- [PASS] SQLite regression suite (70 tests, 1 PostgreSQL test skipped)
- [PASS] Frontend production build with HTTPS API URL
- [PASS] Production source maps disabled

- [ ] Discord SDK authorization succeeds with production credentials
- [ ] Expired/invalid authentication shows a reconnect message without retry loops
- [ ] Practice: bot selection, move, Undo, result, and reconnect
- [ ] Duel: queue join, rating-window updates, cancel, match, and reconnect
- [ ] Duel: both players see the same game and synchronized moves
- [ ] Current Game: waiting, active, completed, and stale game states
- [ ] Result screen shows server-provided result, Rating, and SR only
- [ ] Profile shows real Rating/SR and W/L/D statistics
- [ ] History shows newest-first pagination and safe empty state
- [ ] Leaderboard switches independently between Chess Rating and SR
- [ ] Network loss shows reconnect/retry state; no unsafe move retries
- [ ] 401/403/404/409/422/429/500 responses remain user-safe
- [ ] Narrow Discord Activity/mobile layout has no horizontal overflow
- [ ] Keyboard focus, labels, contrast, and disabled states are usable
- [ ] Production API uses explicit CORS origins and HTTPS security headers
- [ ] No tokens, secrets, databases, logs, or source maps are in frontend artifacts
- [ ] Production domain and Discord Activity URL mapping are verified
