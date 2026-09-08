# Unified Bishoply accounts

Bishoply keeps one canonical row in `users`. Authentication providers are
linked through `auth_identities(provider, subject)`; provider email addresses
are never used to merge accounts. Existing Discord users are backfilled into
this table during normal database initialization, transactionally and
idempotently.

Standalone browser sign-in uses a short-lived, signed OAuth state and a
server-side authorization-code exchange. The resulting Bishoply session is a
30-day HttpOnly cookie (`bishoply_session`) with a separate CSRF cookie for
state-changing web requests. Provider access tokens are never returned to the
browser or stored in localStorage. Discord Activity authentication continues
to use its existing bearer-token flow and resolves the same Discord identity
record.

## Configuration

Required in production:

* `SESSION_SECRET` — high-entropy server-only signing secret.
* `BISHOPLY_FRONTEND_ORIGIN` — the HTTPS browser/Activity origin.
* `BISHOPLY_API_ORIGIN` — the HTTPS API origin used as the OAuth callback base
  (defaults to `https://bishoply.onrender.com` in production).

Optional provider credentials (the corresponding button reports a safe
configuration error until set):

* Google: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
* Apple: `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`,
  `APPLE_PRIVATE_KEY`.
* Website Discord OAuth uses `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET`.

Register callback URLs at each provider as
`{BISHOPLY_API_ORIGIN}/api/auth/{provider}/callback`. Linking a provider is
explicit and rejects an identity already attached to another account.

Apple authorization-code exchange requires the provider's signed client
secret/certificate integration before production credentials are supplied; the
current endpoint fails closed when those credentials are absent.

External Chess.com and Lichess identities are reserved for a future provider
integration and are kept separate from Bishoply Rating and SR.
