"""Small reusable asynchronous Stockfish pool for Practice only."""
import asyncio
import logging
import os
import shutil
import chess.engine
from backend.analysis.config import EXPECTED_ENGINE
from . import config as C
from .stockfish_provider import StockfishProvider

log = logging.getLogger("uvicorn.error")


class EnginePool:
    def __init__(self, size=1):
        self.size = max(1, int(size))
        self._slots = []
        self._available = None
        self._loop = None
        self._lock = asyncio.Lock()

    async def _new_slot(self):
        path = os.getenv('STOCKFISH_PATH') or shutil.which('stockfish')
        if not path:
            raise RuntimeError('Stockfish unavailable')
        transport, engine = await chess.engine.popen_uci(path)
        expected = os.getenv('BISHOPLY_STOCKFISH_VERSION', EXPECTED_ENGINE)
        if engine.id.get('name') != expected:
            transport.close()
            raise RuntimeError('Unexpected Stockfish version')
        await engine.configure({'Threads': 1, 'Hash': 32, 'UCI_ShowWDL': True,
                                'UCI_LimitStrength': False, 'Skill Level': 20})
        log.info("Bishoply Practice engine pool started")
        return {'transport': transport, 'engine': engine, 'provider': StockfishProvider(engine),
                'lock': asyncio.Lock()}

    async def _ensure(self):
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # Async subprocess protocols belong to the loop that created
            # them.  A fresh loop (tests or a dev reload) must discard old
            # slots without attempting to await their closed-loop protocol.
            for slot in self._slots:
                try:
                    slot['transport'].close()
                except Exception:
                    pass
            self._slots = []
            self._loop = loop
            self._available = asyncio.Queue()
        while len(self._slots) < self.size:
            slot = await self._new_slot()
            self._slots.append(slot)
            await self._available.put(slot)

    async def acquire(self):
        await self._ensure()
        slot = await self._available.get()
        return _Lease(self, slot)

    async def release(self, slot, broken=False):
        if broken:
            await self._close_slot(slot)
            try:
                replacement = await self._new_slot()
                self._slots[self._slots.index(slot)] = replacement
                await self._available.put(replacement)
            except Exception:
                if slot in self._slots:
                    self._slots.remove(slot)
            return
        await self._available.put(slot)

    async def _close_slot(self, slot):
        try:
            await asyncio.wait_for(slot['engine'].quit(), .5)
        except Exception:
            slot['transport'].close()

    async def close(self):
        for slot in list(self._slots):
            await self._close_slot(slot)
        self._slots = []
        self._available = None
        self._loop = None


class _Lease:
    def __init__(self, pool, slot):
        self.pool, self.slot = pool, slot
        self.provider = slot['provider']

    async def __aenter__(self):
        await self.slot['lock'].acquire()
        return self.provider, self.slot['engine']

    async def __aexit__(self, exc_type, exc, tb):
        self.slot['lock'].release()
        await self.pool.release(self.slot, broken=exc is not None)
