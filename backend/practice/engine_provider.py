"""Provider-neutral engine contracts for Practice bot moves.

This module contains only Bishoply interfaces and normalized candidate data;
providers may later implement Maia or Lc0 without changing Practice service.
"""
from dataclasses import dataclass
from typing import Protocol, Sequence
import chess


@dataclass(frozen=True)
class Candidate:
    move_uci: str
    move_san: str
    rank: int
    cp: int | None
    mate: int | None
    wdl: list[int] | None
    e2000: int
    pv: list[str]
    legal: bool = True
    tactical_tags: tuple[str, ...] = ()


class EngineProvider(Protocol):
    async def analyze(self, board: chess.Board, *, depth: int | None = None,
                      time: float | None = None, multipv: int = 1,
                      root_moves: Sequence[chess.Move] | None = None) -> list[dict]: ...

    async def play(self, board: chess.Board, *, depth: int | None = None,
                   time: float | None = None) -> chess.Move: ...

    async def health_check(self) -> bool: ...

    async def close(self) -> None: ...
