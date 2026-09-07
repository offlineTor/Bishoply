"""Single engine adapter for review, feedback, hints and bots; no HTTP/FEN API."""
import asyncio
import hashlib
import os
from pathlib import Path
from datetime import datetime, timezone
import shutil
import chess
import chess.engine
from . import config as C


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def outcome(info, color):
    score = info['score'].pov(color)
    mate = score.mate()
    wdl = info.get('wdl')
    raw = list(wdl.pov(color)) if wdl else None
    if raw is not None and (sum(raw) != 1000 or any(type(v) is not int or v < 0 for v in raw)):
        raise ValueError('Invalid engine WDL')
    if mate is not None:
        units = 2000 if score > chess.engine.Cp(0) else 0
    elif raw is not None:
        units = 2 * raw[0] + raw[1]
    else:
        raise ValueError('Engine WDL missing')
    return {'cp': score.score(), 'mate': mate, 'wdl': raw, 'outcome_units': units,
            'outcome': units / 2000, 'win_probability': units / 2000,
            'perspective': 'white' if color else 'black'}


def material(board, color):
    return sum(C.PIECE_VALUES[p.piece_type] * (1 if p.color == color else -1) for p in board.piece_map().values())


class Engine:
    def __enter__(self):
        path = Path(os.getenv('STOCKFISH_PATH') or shutil.which('stockfish') or '')
        if not path.is_file():
            raise RuntimeError('Stockfish unavailable: configure STOCKFISH_PATH')
        self.path = path.resolve()
        self.engine = chess.engine.SimpleEngine.popen_uci(str(self.path), timeout=15)
        try:
            expected = os.getenv('BISHOPLY_STOCKFISH_VERSION', C.EXPECTED_ENGINE)
            if self.engine.id.get('name') != expected:
                raise RuntimeError(f'Expected {expected}; configure and validate this engine version first')
            options = {'Threads': C.THREADS, 'Hash': C.HASH_MB, 'UCI_ShowWDL': True,
                       'UCI_LimitStrength': False, 'Skill Level': 20}
            if os.getenv('BISHOPLY_SYZYGY_PATH'):
                options['SyzygyPath'] = os.environ['BISHOPLY_SYZYGY_PATH']
            self.engine.configure(options)
            effective = {k: v.default for k, v in self.engine.options.items() if v.type != 'button'}
            effective.update(options)
            network = str(effective.get('EvalFile', ''))
            locations = (Path(network), self.path.parent / network)
            network_path = next((p for p in locations if p.is_file()), None)
            self.provenance = {'engine': dict(self.engine.id), 'executable': str(self.path),
                'binary_sha256': checksum(self.path), 'nnue': {'identity': network,
                'sha256': checksum(network_path) if network_path else None,
                'storage': 'external' if network_path else 'embedded or engine-resolved; binary checksum retained'},
                'python_chess': chess.__version__, 'score_protocol': 'latest-score-packet-v1', 'effective_uci_options': effective,
                'classifier_thresholds_e2000': list(C.THRESHOLDS),
                'model_version': C.MODEL_VERSION, 'classifier_version': C.CLASSIFIER_VERSION,
                'accuracy_model_version': C.ACCURACY_VERSION,
                'settings': {'fast_depth': C.FAST_DEPTH, 'normal_depth': C.NORMAL_DEPTH, 'verify_depth': C.VERIFY_DEPTH,
                    'discovery_multipv': C.DISCOVERY_PVS, 'verification_multipv': C.VERIFY_PVS,
                    'candidate_multipv': 1, 'threads': C.THREADS, 'hash_mb': C.HASH_MB,
                    'time_limit': C.SEARCH_SECONDS, 'node_limit': None},
                'timestamp': datetime.now(timezone.utc).isoformat()}
            return self
        except BaseException:
            self.engine.quit()
            raise

    def __exit__(self, *args):
        self.engine.quit()

    def raw_search(self, board, depth, multipv, root_moves):
        # python-chess aggregated analyse() dictionaries retain old bound flags.
        # Keep each latest SCORE packet intact instead; never mix score/depth/PV
        # or a prior iteration's bound status into a newer exact evaluation.
        async def collect():
            analysis = await self.engine.protocol.analysis(board,
                chess.engine.Limit(depth=depth, time=C.SEARCH_SECONDS),
                multipv=multipv, root_moves=root_moves, game=object())
            latest = {}
            try:
                async for info in analysis:
                    if 'score' in info:
                        latest[info.get('multipv', 1)] = dict(info)
                await analysis.wait()
                return [latest[key] for key in sorted(latest)]
            finally:
                analysis.stop()
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(collect(), C.SEARCH_SECONDS + 15), self.engine.protocol.loop)
        return future.result()

    def search(self, board, depth, multipv=1, root_moves=None):
        if not board.is_valid():
            raise ValueError('Invalid board')
        self.engine.configure({'Clear Hash': None})
        infos = self.raw_search(board, depth, multipv, root_moves)
        if not infos or any(i.get('depth', 0) < depth or not i.get('pv') for i in infos):
            raise RuntimeError('Search did not complete required depth; no classification published')
        if any(i.get('lowerbound') or i.get('upperbound') for i in infos):
            raise RuntimeError('Bound-only score cannot be classified')
        if len(infos) != min(multipv, len(root_moves) if root_moves else board.legal_moves.count()):
            raise RuntimeError('Incomplete candidate set')
        result = []
        for info in infos:
            if root_moves and info['pv'][0] not in root_moves:
                raise RuntimeError('Engine ignored restricted candidate')
            pv_board = board.copy()
            san = []
            for move in info['pv']:
                if move not in pv_board.legal_moves:
                    raise RuntimeError('Illegal engine PV')
                san.append(pv_board.san(move))
                pv_board.push(move)
            result.append({**outcome(info, board.turn), 'move': info['pv'][0].uci(),
                'pv_uci': [m.uci() for m in info['pv']], 'pv': san, 'root_fen': board.fen(),
                'depth': info['depth'], 'seldepth': info.get('seldepth'), 'nodes': info.get('nodes'),
                'time': info.get('time'), 'tbhits': info.get('tbhits', 0), 'multipv': multipv,
                'restricted_root_moves': [m.uci() for m in root_moves] if root_moves else None,
                'material_gain': material(pv_board, board.turn) - material(board, board.turn)})
        return result

    def candidates(self, board, played, depth, count, retain=()):
        discovery = self.search(board, depth, min(count, board.legal_moves.count()))
        roots = sorted({x['move'] for x in discovery} | {played.uci()} | set(retain))
        # Every scored alternative uses SAME ROOT, SAME DEPTH and SINGLE-PV.
        candidates = [self.search(board, depth, 1, [chess.Move.from_uci(uci)])[0] for uci in roots]
        def rank(candidate):
            mate = candidate['mate']
            kind = 1 if mate is not None and mate > 0 else -1 if mate is not None else 0
            tie = -mate if mate is not None else candidate['cp']
            return candidate['outcome_units'], kind, tie
        candidates.sort(key=rank, reverse=True)
        for rank, candidate in enumerate(candidates, 1):
            candidate['rank'] = rank
        return {'discovery': discovery, 'candidates': candidates, 'depth': depth}

    # Canonical adapter surface used by Bishoply Intelligence V1 consumers.
    def analyze_root(self, board, *, depth, multipv=3):
        return self.search(board, depth, multipv)

    def analyze_candidates(self, board, *, depth, multipv=3, root_moves=None):
        return self.search(board, depth, multipv, root_moves)

    def verify_move(self, board, move, *, depth=C.VERIFY_DEPTH, multipv=C.VERIFY_PVS):
        return self.candidates(board, move, depth, multipv)
