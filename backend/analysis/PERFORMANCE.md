# Result and review performance audit

Measured locally with Stockfish 19, Threads=1, Hash=64 MB; these short fixtures
are engineering checks, not a calibrated latency guarantee. Tests and another
Stockfish process ran during parts of measurement, so hardware/load effects are
not controlled. No production game was created or analyzed for these measurements.

## Separate normal and fast pass cost

Common-root candidate discovery (MultiPV4) plus every restricted candidate,
White's e4 from the initial position and Black's e5 after e4:

| Root/player move | Depth 12 | Depth 20 (without depth-24 verification) |
| --- | ---: | ---: |
| Initial position / e4 | 0.354 s | 8.638 s |
| After e4 / e5 | 0.478 s | 10.544 s |
| Mean per ply | 0.416 s | 9.591 s |

A separate startup measured 0.672 s. Ten Clear Hash + isready cycles averaged
0.0051 s each. UCI new-game reset cost is included in the search timings; it was
not separately isolated. Full reset/reinitialization is not the main cost here.

## Complete review comparison

The baseline below runs the previous depth-20/24, all-at-once algorithm with the
score-packet fix applied. The original uncorrected adapter failed on the first
fixture because a stale bound flag survived in an aggregated exact result.

| Fixture | Plies | Baseline: first usable analysis / total | New first fast ply | All fast plies | New total authoritative |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fool's mate | 4 | 227.345 s | 0.653 s | 2.132 s | 229.770 s |
| Six-ply opening | 6 | 231.123 s | 0.579 s | 3.377 s | 236.662 s |

For this fixture all four plies required verification. Baseline mean per ply,
including depth 24, was 56.836 s; fast mean including startup was 0.533 s.
The opening fixture verified five of six plies; its baseline mean was 38.521 s
per ply including verification, and its fast mean was 0.563 s including startup.
Final move labels matched for both games. The improvement is **time to useful analysis**, not
less authoritative computation. Replay itself renders immediately from game
history, before any engine result. Browser polling can add up to two seconds
plus queue wait to observing a published row.

These full-job measurements use `run_review(..., publish=...)` with one engine
for both tiers, to isolate search and publication overhead. The production queue
splits tiers into independent fast/deep lanes and starts one engine per tier,
adding one startup per game. It avoids blocking new fast reviews behind an older
game's deep job. Each engine is reused for every position in its tier; none is
restarted per move or candidate. This is not a production end-to-end benchmark.

## Search, batching and persistence decisions

- Sequential fast pass supplies useful moves in game order. Deep updates replace
  individual rows in that same order. No speculative move prioritization.
- Common-root searches retain single-PV matched candidate settings and fresh
  hash/new-game state. Sharing transposition state between candidate comparisons
  was not adopted merely to improve benchmark numbers.
- Normal depth 20 and verification depth 24 are unchanged. Tactical/mate,
  threshold adjacency, evaluation swings, PV instability and candidate-order
  uncertainty still trigger verification. These triggers often fire, explaining
  why deep cost is much higher than depth 20 alone.
- Full raw evidence stays in the existing revision JSON. Polling omits large raw
  pass trees; result/progress snapshots are committed after each ply. Completed
  current-version reviews are read from storage, without another engine job.
- Partial data survives reopening and failures. A failed move does not prevent
  other moves being analyzed; Accuracy remains unavailable until the entire
  authoritative review succeeds. Interrupted analyzing jobs require retry;
  queued deep tiers survive restart.
- One process each for fast, deep and Practice feedback; bots/hints retain their
  separate bounded concurrency. This is a single-API-process deployment, not a
  distributed queue. Queue delay and long games remain practical limitations.

## Reproduce

`.venv/bin/python -m scripts.benchmark_review`

`.venv/bin/python -c 'from scripts.benchmark_review import profile; profile()'`

Raw reports are written to `/tmp/bishoply-review-benchmark.json` and
`/tmp/bishoply-review-profile.json`. Neither command imports the database.

Raw results and profile are retained in `benchmark_results.json`.
