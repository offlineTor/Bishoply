# Bishoply Chess Knowledge Engine

This package is the semantic layer above Bishoply Intelligence V1. It observes
the existing `python-chess` board and already computed common-root candidates;
it never starts Stockfish or changes evaluation, classification, Accuracy, rating,
or SR. Every claim includes board or move evidence. Emma and future personas
consume this result rather than embedding chess rules in presentation code.

Version 3 provides deterministic phase detection, material context, expanded
pawn and king-safety facts, verified checks/captures/promotions, forks and
double attacks, discovered checks/attacks, pins, move purposes, strategic file
and activity facts, structured reasoning, and MultiPV criticality evidence.
Opening recognition is intentionally `unknown` until a configured
Polyglot/book source supplies a real name/ECO. Sacrifice, Great, and Brilliant
remain evidence foundations only and are disabled. `CoachContext` is a bounded
per-game state object (six recent plies) that records issue counters, detected /
repeated / resolved lifecycle, corrections, and prior coaching facts. It is
persona-independent and serializable with `to_dict()` / `from_dict()`.
Practice feedback checkpoints this state in the Practice-owned
`practice_coach_context` table. Saves are monotonic by revision and ply, so
retries and late workers cannot double-count or overwrite newer context.

`emma.py` is a separate persona layer. `compose_emma()` consumes
classification, knowledge, evaluation, and context, then returns a compact
message, deterministic message key, priority, and speech decision. Routine
Good moves are silent; high-priority mistakes and verified continuity events
can be spoken by the existing transport.

The result schema is `bishoply-chess-knowledge-v3`. No additional engine calls
are introduced; callers pass existing Intelligence candidates when available.
Board-only strategic facts include center occupation/control, bishop pair,
open/semi-open files, per-piece attack counts, and basic material/king-safety
context. Tactical claims are deliberately conservative: geometry alone is not
enough to claim a winning tactic.
