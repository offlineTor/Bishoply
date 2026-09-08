"""Stockfish provider adapter used only by unrated Practice."""
import chess
from .engine_provider import EngineProvider


class StockfishProvider(EngineProvider):
    def __init__(self, engine):
        self.engine = engine

    async def analyze(self, board, *, depth=None, time=None, multipv=1, root_moves=None):
        limit = chess.engine.Limit(depth=depth, time=time)
        return await self.engine.analyse(board, limit, multipv=multipv,
                                         root_moves=list(root_moves) if root_moves else None,
                                         game=object())

    async def play(self, board, *, depth=None, time=None):
        result = await self.engine.play(board, chess.engine.Limit(depth=depth, time=time), game=object())
        return result.move

    async def health_check(self):
        return self.engine is not None

    async def close(self):
        return None
