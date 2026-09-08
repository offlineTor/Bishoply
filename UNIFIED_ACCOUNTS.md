# Unified Accounts V1

Bishoply resolves Discord Activity bearer identities and website OAuth sessions
to the same canonical `users.id`. Provider credentials and tokens stay on the
backend; the browser receives only an HttpOnly session cookie.

Production callback URLs:

- Discord: `https://bishoply.onrender.com/api/auth/discord/callback`
- Google: `https://bishoply.onrender.com/api/auth/google/callback`
- Apple: `https://bishoply.onrender.com/api/auth/apple/callback`

Required provider configuration is server-side: `DISCORD_CLIENT_ID`,
`DISCORD_CLIENT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and Apple
Sign in with Apple credentials (`APPLE_CLIENT_ID`, `APPLE_TEAM_ID`,
`APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`). Missing Google or Apple credentials fail
with a provider-specific configuration error.

Username changes are initially free; later changes require a verified $2.99
payment intent. The current payment adapter is intentionally fail-closed until
a signed webhook provider is configured. Cosmetic ownership and loadouts are
stored against the canonical Bishoply user and cannot affect chess gameplay,
rating, SR, or matchmaking.
