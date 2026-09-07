"""Read-only Stockfish benchmark; never imports database or creates games.
Run from root: .venv/bin/python -m scripts.benchmark_review
"""
import json
from pathlib import Path
import time
import chess
from backend.analysis.worker import run_review


def fixture(ucis):
    board=chess.Board(); moves=[]
    for ply,uci in enumerate(ucis.split(),1):
        move=chess.Move.from_uci(uci); san=board.san(move); board.push(move)
        moves.append({'ply':ply,'uci':uci,'san':san,'fen_after':board.fen()})
    return {'starting_fen':chess.STARTING_FEN,'current_fen':board.fen(),'mode':'casual'},moves


def main():
    reports=[]
    for name,ucis in [('fools_mate','f2f3 e7e5 g2g4 d8h4'),('opening','e2e4 e7e5 g1f3 b8c6 f1b5 a7a6')]:
        game,moves=fixture(ucis)
        start=time.monotonic()
        old=run_review(game,moves)
        old_seconds=time.monotonic()-start
        start=time.monotonic(); first=[]; fast_end=[]; updates=[]
        def publish(result):
            at=time.monotonic()-start
            if result['stage']=='fast_analysis' and result['analyzed_plies']:
                if not first: first.append(at)
                if result['analyzed_plies']==len(moves): fast_end.append(at)
            updates.append({'stage':result['stage'],'plies':result['analyzed_plies'],'seconds':round(at,3)})
        new=run_review(game,moves,publish=publish)
        new_seconds=time.monotonic()-start
        report={'game':name,'plies':len(moves),'baseline_authoritative_total_seconds':old_seconds,
            'baseline_authoritative_average_seconds_per_ply':old_seconds/len(moves),
            'first_fast_ply_seconds':first[0], 'fast_pass_seconds':fast_end[0],
            'fast_average_seconds_per_ply':fast_end[0]/len(moves),
            'progressive_total_seconds':new_seconds,'authoritative_stage_seconds':new_seconds-fast_end[0],
            'verified_plies':sum(m['verification_occurred'] for m in new['moves']),
            'same_final_labels':[m['classification'] for m in old['moves']]==[m['classification'] for m in new['moves']],
            'engine':new['engine'],'settings':new['settings'],'updates':updates}
        reports.append(report)
        print(json.dumps(report),flush=True)
        Path('/tmp/bishoply-review-benchmark.json').write_text(json.dumps(reports,indent=2))

if __name__=='__main__': main()


def profile():
    """Isolate normal-depth cost and UCI initialization/reset overhead."""
    from backend.analysis.engine import Engine
    started=time.monotonic()
    with Engine() as engine:
        startup=time.monotonic()-started
        reset_start=time.monotonic()
        for _ in range(10):
            engine.engine.configure({'Clear Hash':None})
            engine.engine.ping()
        reset=(time.monotonic()-reset_start)/10
        timings=[]
        board=chess.Board()
        for uci in ('e2e4','e7e5'):
            move=chess.Move.from_uci(uci)
            for depth in (12,20):
                start=time.monotonic()
                engine.candidates(board,move,depth,4)
                row={'move':uci,'depth':depth,'seconds':time.monotonic()-start}
                timings.append(row);print(json.dumps(row),flush=True)
            board.push(move)
        result={'startup_seconds':startup,'clear_hash_plus_ping_seconds':reset,'timings':timings}
        Path('/tmp/bishoply-review-profile.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
