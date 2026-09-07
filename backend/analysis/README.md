# Bishoply analysis correctness stage

This stage implements common-root comparisons, exact thresholds, forced moves,
engine provenance, immutable review revisions, and Book/Miss foundations.
The [Practice backend](../practice/README.md) now uses this same analysis engine
for stored player moves and completed Practice reviews. Practice UI is not implemented here.
Great and Brilliant are disabled in
all modes: their names are reserved, with no awarding branch.

## Opportunity loss and search contract

Stockfish WDL is validated as three nonnegative integers summing to 1,000.
Expected-score units are `E2000 = 2 * wins + draws`; normalized expectation is
`E2000 / 2000`. For mate, the separate signed mate field is retained before
assigning scalar outcome units. Both evaluations use the mover's perspective.

MultiPV discovers four candidates at depth 20 (six at verification depth 24).
The played move is always included. Every discovered candidate, the played move,
and retained first-pass candidates are then independently evaluated from the
**same pre-move board with full history**, depth, single-PV, and reset state,
using `root_moves=[candidate]`. Ranking uses outcome units, mate status/distance,
then centipawns. Loss is `max(0, best_units - played_units)`. The chosen best
candidate necessarily has zero loss; a sole legal move is explicitly Forced
with zero loss regardless of search output.

`evaluation_after` now means the played candidate's **common-root** evaluation,
not an independent child-board search. Its `root_fen` and the explicit
`evaluation_after_semantics` field record this distinction. The actual child
FEN is still stored for replay. Existing frontend category counts and evaluation
wording have not been changed in this backend-only stage.

Thresholds are centralized in `config.py`, inclusive and integer-only:

| Label | Maximum loss units | Normalized maximum |
| --- | ---: | ---: |
| Best | 10 | .005 |
| Excellent | 30 | .015 |
| Good | 80 | .040 |
| Inaccuracy | 160 | .080 |
| Mistake | 360 | .180 |
| Blunder | 2000 | 1.000 |

No floating-point number is used to choose a threshold. Floats are used only
for display and the aggregate Accuracy formula.

## Verification and special-label foundation

A deeper matched pass runs for threshold adjacency (within four units), mate
scores, captures/checks/promotions, candidate material gains of at least 300
material units, loss of at least 100 outcome units, discovery/scoring disagreement
of at least 100 units, first-three-ply PV disagreement, or a top-two outcome gap
of at most ten units. All candidates from the first pass are retained.
The deeper pass is authoritative. Missing depth, incomplete candidate sets,
illegal PVs and bound-only scores fail without a final classification.

Miss requires deeper verification, unchanged best candidate, less than 100 units
of cross-pass score disagreement, and matching first-three-ply best/played PVs.
It identifies loss of a verified forced mate, or a best continuation gaining at
least 300 material units when the played continuation gains at least 300 less,
best expectation is at least 1300/2000, and opportunity loss is at least 160 units.
Evidence includes candidates, lines and the opportunity type. This is an
**experimental foundation**, not a validated tactical-proof system: PV-endpoint
material gains still require a larger tactical validation corpus.

Book is possible only for an internal `practice=True` analysis and exact move
membership with positive weight in `BISHOPLY_POLYGLOT_BOOK`. No book is bundled.
A configured Polyglot file's name/checksum and matching move are recorded.
Optional `<book>.bin.json` metadata maps `zobrist_hex:uci` to `opening_name` and
`eco`; absent metadata stays null. Engine scores never create Book labels.

## Mate, draws, and experimental Accuracy

Mate distance and transitions are retained separately. Losing a forced mate can
be Miss even when saturated outcome units hide the loss. Sound longer mates are
not penalized for distance alone. Automatic terminal outcomes and claimable
threefold/fifty-move states are recorded; claims are not silently made. A broader
mate/draw policy and tablebase validation remain future work.

`accuracy.py` is versioned and explicitly experimental. For included decisions:
`100 * exp(-4 * sqrt(sum(weight * (loss_units/2000)^2) / sum(weight)))`, rounded
to one decimal. Forced, Book and assisted moves are excluded. Mate preservation,
shortening/lengthening and terminal checkmate are excluded. Lost mate uses at
least 360 loss units. Positions already at <=40 or >=1960 units are excluded
when they remain decided and lose <=40 units; otherwise they have weight .25.
In-check responses have weight .5; other decisions have weight 1. No included
decisions yields null. Dead moves therefore cannot dilute the denominator.
These policies still require calibration against independently reviewed games.

## Engine provenance and settings

Default required identity: `Stockfish 19`; an intentional engine change requires
`BISHOPLY_STOCKFISH_VERSION` and revalidation. `STOCKFISH_PATH` selects the binary.
Use one thread, 64 MB hash, full strength, WDL enabled, Clear Hash and a new game
marker per search. Each search has a 45-second budget with 15 seconds of protocol
grace; insufficient depth fails. Review budget is one hour, checked between plies.
No fixed node limit is configured. Optional `BISHOPLY_SYZYGY_PATH` enables tables.

Persist engine identity, resolved executable, SHA-256, NNUE identity and external
checksum when available (embedded NNUE is covered by the binary checksum), library
version, effective UCI options, exact thresholds and model/classifier/Accuracy
versions. Both passes retain raw WDL, cp/mate, full SAN/UCI PVs, candidate ranking,
root restrictions, depth, selective depth, nodes, time and tablebase hits.
Cached results are repeatable reads; determinism across builds/hardware is not
claimed. MultiPV discovery is not an exhaustive proof over all legal moves.

## Storage, revisions, and fair play

Startup safely adds `analysis_revisions` and imports completed legacy
`game_analysis` rows once, without modifying them. A new model or failed attempt
creates a new revision. `POST .../analysis?new_revision=true` requests another;
old complete results remain immutable in code and internally queryable. The newest
complete result for the current model/classifier/Accuracy version is returned;
a prior authoritative revision remains readable while its replacement is queued.
Legacy model results remain for audit but are not silently displayed as v2.

Multiplayer GET and POST, worker execution and publication require a completed
game. Practice endpoints require a Practice table record and its access key;
feedback accepts only an already stored player move. No endpoint accepts FEN.
Separate thread-backed worker lanes process fast reviews, deep reviews and after-move feedback.
Queue capacity is eight per review subject type and 32 feedback jobs; deployment
still assumes one API process. Restart marks interrupted jobs failed.
No competitive game/rating/transaction rows are edited by analysis.

## Checks

`.venv/bin/python -m compileall -q backend/analysis backend/api/analysis.py tests`

`.venv/bin/python -m unittest discover -s tests -v`

Tests use isolated SQLite, real Stockfish White/Black mate positions, common-root
and depth contracts, exact boundaries, Book membership, Miss evidence, forced
exclusion, repeatability, revisions/legacy migration and active-game rejection.
They do not establish public calibration or validate Great/Brilliant.

Sources: [python-chess engine API](https://python-chess.readthedocs.io/en/latest/engine.html),
[Polyglot reader](https://python-chess.readthedocs.io/en/latest/polyglot.html),
[Stockfish 19 WDL implementation](https://raw.githubusercontent.com/official-stockfish/Stockfish/sf_19/src/uci.cpp).

## Progressive Current Game review

Completed-game HTTP jobs now have a sequential depth-12 common-root fast tier,
then the unchanged depth-20/24 authoritative tier. Fast rows explicitly carry
`preliminary=true`, `authoritative=false`; no shallow Miss, Great or Brilliant is
awarded. Accuracy is withheld until all required authoritative moves succeed.
Thresholds, expected-outcome conversion and accuracy formula are unchanged.

The result overlay and replay board use game state/history only. Requesting
review opens replay immediately; polls occur every two seconds while visible
(five seconds in a background document). Each successful ply is persisted before
moving on. Incoming analysis updates labels without selecting a new board square
or resetting the move-list scroll position. A failed verification leaves the
preliminary move available, continues with other moves and marks the job failed
rather than presenting a partial result as final.

Database status retains `queued/analyzing/complete/failed` for compatibility.
The result JSON adds pipeline `progressive-v1`, stage, processed/analyzed/total
plies, percentage, authoritative count and failed plies. HTTP maps an analyzing
job to `fast_analysis` or `deep_analysis`. A finished fast tier is requeued as
`deep_queued` in the same revision. No new table or column migration is required.
Partial results survive requests/reopening and are retained on failure.
Completed current-model revisions remain cached; explicit retries/new revisions
preserve older records. A restart fails interrupted work but retains its partial
JSON; queued deep work remains resumable.

Separate fast, deep and Practice-feedback worker lanes prevent a deep review
from blocking new fast passes. Each tier opens one controlled Stockfish process
and reuses it across all its positions; a full queued review therefore has two
engine startups, never one per ply. Each engine uses one thread. Existing
bot/hint concurrency is independent. Deployment still assumes one API process.
Fast queues can still wait behind other fast jobs; this is not a latency SLA.

Common-root candidate comparison still resets hash/new-game state per search.
No transposition-table sharing between independently scored alternatives is
introduced. Full raw evidence is stored in SQLite; review polling omits the two
large raw pass trees to reduce repeated transfers. Practice feedback retains its
existing response contract. The latest score packet is now read from the UCI
stream: python-chess aggregated dictionaries can retain stale bound flags from
older iterations. Actual bound-only final packets, insufficient depth and missing
WDL still fail closed. Protocol timeout remains 45 seconds plus 15 seconds grace.

All multiplayer publication points, including partial updates, require completed
status. Practice live feedback remains allowed only for stored Practice moves.
The centralized frontend `game-result.js` formats checkmate, resignation, timeout,
stalemate, threefold/fivefold repetition, fifty/75-move rules, insufficient
material, agreement and abort/cancellation without leaking enum names. Timeout,
threefold/fifty-move claims, agreement and cancellation labels do not add clock,
claim or agreement networking. Rematch is hidden until an opponent consent flow
exists. Multiplayer move processing now replays history so existing automatic
fivefold repetition detection actually receives repetition counts.

See `PERFORMANCE.md` for measured timings and limits. Additional validation:
`node tests/result_formatter.mjs`, and `node tests/browser_current_game.mjs`
against the isolated browser API/Vite servers documented in that test.

## Bishoply Intelligence V1

`intelligence.py` is the canonical layer above Stockfish. It retains Stockfish
19 WDL as the primary signal: `E2000 = 2*win + draw`, with integer units from
0 to 2000. A move's opportunity loss is `max(0, best_E2000 - played_E2000)`
from the same side-to-move root; forced moves have exactly zero loss. The
versioned Move Accuracy formula is:

`round(clamp(0,100, 100 * exp(-4 * loss_E2000 / 2000)))`

Book, assisted, and forced moves are excluded from accuracy aggregation. Game
Accuracy v1 uses the existing decision weights (1.0, 0.5 forced-tactical,
0.25 already-decided), computes the weighted arithmetic Move Accuracy mean,
then blends that mean with the weighted harmonic mean and applies a bounded
volatility factor: `((arithmetic + harmonic) / 2) * (1 - 0.12 * max_loss/2000)`.
The result is versioned as `bishoply-game-accuracy-v1-volatility`; this is
experimental and is not Chess.com Accuracy.

The new result fields are additive and include canonical evaluation data,
integer WDL-derived probabilities, top candidates, concepts, structured hints,
and deterministic Emma evidence. Great and Brilliant remain disabled. The
existing pipeline remains authoritative unless consumers opt into the
`BISHOPLY_INTELLIGENCE_V2=1` migration flag; no frontend migration is made in
this phase.
