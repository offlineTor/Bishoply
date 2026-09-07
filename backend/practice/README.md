# Bishoply Practice backend

Practice is unrated and stored separately. No Practice service calls competitive
creation, outcome, rating, SR, transaction, streak or leaderboard services.
`CREATE TABLE IF NOT EXISTS` at API startup adds `practice_games` and
`practice_moves`; shared `analysis_revisions` already supports Practice subjects.
Existing production data is not rewritten. Deploy with one API process.

## API and ownership

All routes below have prefix `/api/practice`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/bots` | Public roster and experimental calibration settings |
| POST | `/games` | Create with `discord_id`, `bot_id`, `player_color` |
| GET | `/games/{id}` | State, legal player moves and move history |
| POST | `/games/{id}/move` | Legal player UCI `move` and `expected_ply` |
| POST | `/games/{id}/bot-move` | Bot response at `expected_ply` |
| POST | `/games/{id}/hint` | Sequential `stage` 1–3 at `expected_ply` |
| POST | `/games/{id}/resign` | End Practice with opponent winning |
| GET/POST | `/games/{id}/analysis/{ply}` | Poll/request stored player-move feedback |
| GET/POST | `/games/{id}/review` | Poll/request completed shared review |

Creation verifies `Authorization: Bearer <Discord OAuth access token>` against
Discord `/users/@me` and requires an existing Bishoply user. It returns a random
`access_key` once; retain it privately. Subsequent game routes require
`X-Practice-Key`; the database stores only its SHA-256 hash. No key recovery/list
flow is provided yet. Request bodies reject unknown fields, including arbitrary
FENs. Rated/casual game IDs cannot resolve in these routes. Existing multiplayer
review routes still require completed status at request, execution and publication.

A player move atomically persists its feedback job. Poll for `queued`,
`analyzing`, `complete` or `failed`; final feedback includes classification,
evaluation, verification and evidence from the shared depth-20/24 engine.
Allowed labels are Best, Excellent, Good, Inaccuracy, Mistake, Blunder, Miss,
Book and Forced. Great/Brilliant remain disabled. Miss/Accuracy are experimental;
Book requires a real configured Polyglot file (none bundled).

The client calls `bot-move` when `needs_bot_move` is true, including White's opening
move when the player chooses Black. Stale ply, wrong turn and concurrent engine
operations reject without applying a move. Resignation invalidates in-flight bot
results. Automatic python-chess terminal outcomes are persisted; claimable draws
are not automatically claimed. Full repetition history is replayed.

Hints reveal source square, then destination square, then UCI/SAN recommendation.
Stages cannot be skipped; repeats are idempotent. Hints record counts and assisted
moves, which shared Bishoply Accuracy excludes. Private bot candidate evidence
and cached hint recommendations are omitted from normal game responses.

## Estimated Bot Strength and controlled weakening

`config.py` is the single calibration module. Display values are **Estimated Bot
Strength**, not measured Elo or any federation/site rating. Each game snapshots
its bot configuration. Original temporary transparent PNGs live at
`frontend/public/assets/bots/{bot_id}.png`; regenerate with
`python3 scripts/generate_bot_placeholders.py`.

| Bot | Estimated strength | Candidates | Max cp loss | Max E2000 loss | Style probability |
| --- | ---: | ---: | ---: | ---: | ---: |
| Scout | 600 | 8 | 220 | 300 | .80 |
| Tempo | 800 | 7 | 180 | 260 | .65 |
| Fork | 1000 | 6 | 150 | 220 | .55 |
| Gambit | 1200 | 6 | 120 | 180 | .50 |
| Castle | 1400 | 5 | 90 | 140 | .40 |
| Tactician | 1600 | 5 | 70 | 100 | .35 |
| Endgame | 1800 | 4 | 60 | 80 | .30 |
| Vanguard | 2000 | 4 | 40 | 60 | .20 |
| Maestro | 2200 | 3 | 25 | 40 | .15 |
| Crown | 2400 | 1 | 0 | 0 | 0 |

Required engine identity defaults to Stockfish 19 (`STOCKFISH_PATH` selects binary).
Jobs use Threads=1, Hash=32 MB, WDL enabled and full Skill Level=20. Non-Crown bots
first request a 0.20-second move with UCI_LimitStrength=true and UCI_Elo clamped
to the engine's advertised range (installed Stockfish 19: 1320–3190). Thus
600–1200 clamp to 1320; additional bounded candidate weakening differentiates
these bots. UCI settings are controls, not a calibrated strength conversion.

Full-strength MultiPV then assesses candidates to depth 10 or 0.35 seconds,
whichever comes first. A missing base move is separately root-scored with the
same limits. Both cp and E2000 guardrails constrain selection; preserve known
winning mates and avoid known losing mates when a safe candidate exists.
These short assessments do not supply review classifications or prove safety.

On a stylistic draw, candidate weight is `exp(-rank/temperature +
0.6*clamp(style_score,-3,3))`, rank zero-based; temperature is 3 for Scout,
2 for other bots <=1200, .8 otherwise. Otherwise retain the UCI base move if
inside the band, falling back to the best eligible candidate. The seed is derived
from game ID and ply; time-limited engine searches can still vary across runs.
Style bonuses favor development, knight forks, checks/captures, king safety or
technical play. They never permit moves outside the scored legal band.

Endgame uses `f=min(1,total non-king material/6000)`, adds `round(300*(1-f))`
to its requested UCI setting, multiplies quality caps by `max(.15,f)` and style
probability by `f`. Crown disables UCI strength limiting and searches to depth
18 or .8 seconds, without stylistic weakening. Its displayed 2400 remains
uncalibrated and is not a promise of measured performance.

## Resource limits and validation

At most two bot/hint engine jobs run concurrently. An 8-second deadline includes
waiting for a slot; subprocess cleanup has a short bounded grace period.
Timeouts/errors return 503, release the operation claim and preserve the board.
There is no random-move fallback. Hints search at depth 14 or .5 seconds.
Per-owner creation caps active games at ten; history caps at 1,000 plies.
A full 32-job feedback queue rejects and rolls back new player moves with 429.
Review and feedback run in separate background threads with separate engines;
feedback may be delayed by deep verification. Pending operations are released
and interrupted analysis marked failed on backend restart.

Run `.venv/bin/python -m unittest discover -s tests -v` and
`.venv/bin/python -m compileall -q backend auth_server.py tests`.
Tests use temporary SQLite, compare all competitive tables before/after Practice,
exercise both bot colors with real Stockfish, real shared feedback/review, access
controls, hint stages, stale requests, timeouts and resignation races.

Limitations: no UI integration, strength calibration, claim-draw endpoint,
account-based key recovery or distributed workers yet. Candidate heuristics need
a broader positional test corpus. No public-quality claims for bot strengths,
Miss or Bishoply Accuracy follow from these tests.
