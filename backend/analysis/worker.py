"""Authoritative common-root pipeline. Shared by feedback and BOTH review modes."""
from datetime import datetime, timezone
import time
import os
import chess
from . import config as C
from .engine import Engine
from .accuracy import measure
from .book import lookup
from .model import classify_move
from .intelligence import move_accuracy, game_accuracy, SCHEMA_VERSION, intelligence_result
from .concepts import extract, coach_for
from backend.chess_knowledge import CoachContext, analyze_position
from backend.chess_knowledge.emma import compose_emma, game_summary


def verification_reasons(board, move, first):
    cs = first['candidates']
    best = cs[0]
    played = next(c for c in cs if c['move'] == move.uci())
    loss = max(0, best['outcome_units'] - played['outcome_units'])
    reasons = []
    if any(abs(loss - boundary) <= C.BOUNDARY_MARGIN for boundary, _ in C.THRESHOLDS):
        reasons.append('threshold_adjacent')
    if any(c.get('mate') is not None for c in cs):
        reasons.append('mate_transition')
    if board.is_check() or board.is_capture(move) or board.gives_check(move) or move.promotion or any(c.get('material_gain', 0) >= C.MATERIAL_GAIN for c in cs):
        reasons.append('tactical_position')
    if loss >= C.DISAGREEMENT:
        reasons.append('major_evaluation_swing')
    for discovered in first['discovery']:
        scored = next(c for c in cs if c['move'] == discovered['move'])
        if abs(scored['outcome_units'] - discovered['outcome_units']) >= C.DISAGREEMENT:
            reasons.append('large_engine_disagreement')
        if scored['pv_uci'][:3] != discovered['pv_uci'][:3]:
            reasons.append('pv_instability')
    if len(cs) > 1 and best['outcome_units'] - cs[1]['outcome_units'] <= C.ORDER_MARGIN:
        reasons.append('unclear_candidate_ordering')
    return sorted(set(reasons))


def analyze_move(engine, board, move, *, practice=False, revision=1, assisted=False, preliminary=False,
                 coach_context=None, ply=None):
    if move not in board.legal_moves:
        raise ValueError('Illegal played move')
    first = engine.candidates(board, move, C.FAST_DEPTH if preliminary else C.NORMAL_DEPTH, C.DISCOVERY_PVS)
    reasons = verification_reasons(board, move, first)
    final = first
    if reasons and not preliminary:
        final = engine.candidates(board, move, C.VERIFY_DEPTH, C.VERIFY_PVS,
                                  retain=[c['move'] for c in first['candidates']])
    first_by_move = {c['move']: c for c in first['candidates']}
    final_by_move = {c['move']: c for c in final['candidates']}
    disagreements = {uci: abs(c['outcome_units'] - final_by_move[uci]['outcome_units']) for uci, c in first_by_move.items()}
    # Special labels fail closed on rank / PV / outcome instability across passes.
    stable = (first['candidates'][0]['move'] == final['candidates'][0]['move'] and
              max(disagreements.values(), default=0) < C.DISAGREEMENT and
              first_by_move[move.uci()]['pv_uci'][:3] == final_by_move[move.uci()]['pv_uci'][:3] and
              first['candidates'][0]['pv_uci'][:3] == final['candidates'][0]['pv_uci'][:3])
    book = lookup(board, move) if practice else None
    quality = classify_move(board, move, final['candidates'], verified=bool(reasons) and not preliminary, stable=stable,
                            practice=practice, book=book)
    best, played = final['candidates'][0], final_by_move[move.uci()]
    child = board.copy()
    san = child.san(move)
    child.push(move)
    result = {**quality, 'model_version': C.MODEL_VERSION, 'classifier_version': C.CLASSIFIER_VERSION,
            'accuracy_model_version': C.ACCURACY_VERSION, 'engine_version': engine.provenance['engine']['name'],
            'analysis_revision': revision, 'timestamp': datetime.now(timezone.utc).isoformat(),
            'color': 'white' if board.turn else 'black', 'move_number': board.fullmove_number,
            'fen_before': board.fen(), 'fen': child.fen(), 'played_move': move.uci(), 'san': san,
            'best_move': best['move'], 'pv': best['pv'], 'pv_uci': best['pv_uci'],
            'evaluation_before': best, 'evaluation_after': played,
            'evaluation_after_semantics': 'played move evaluated from the SAME pre-move root',
            'white_outcome': played['outcome'] if board.turn else 1-played['outcome'],
            'assisted': assisted, 'verification_occurred': bool(reasons) and not preliminary,
            'preliminary': preliminary, 'authoritative': not preliminary,
            'verification': {'reasons': reasons, 'stable': stable, 'outcome_disagreements': disagreements,
                             'normal_pass': first, 'authoritative_pass': final}}
    result['move_accuracy'] = move_accuracy(result['loss_units'], forced=result['forced_move'],
        book=bool(result.get('book')), mate_transition=result['mate_policy'].get('transition'))
    result['intelligence_schema_version'] = SCHEMA_VERSION
    result['intelligence_feature_flag'] = os.getenv(C.INTELLIGENCE_FEATURE_FLAG, '').lower() in ('1', 'true', 'on')
    result['win_probability_before'] = best['outcome_units'] / 2000
    result['win_probability_after'] = played['outcome_units'] / 2000
    result['win_probability_loss'] = result['loss_units'] / 2000
    result['candidates'] = [{**candidate, 'win_probability': candidate['outcome_units'] / 2000}
                            for candidate in final['candidates']]
    result['concepts'] = extract(board, move, material_delta=played.get('material_gain', 0))
    result['threats'] = []
    result['hint'] = {'concept': result['concepts'][0]['topic'] if result['concepts'] else 'best_move',
                      'source_square': best['move'][:2], 'target_square': best['move'][2:4],
                      'move_san': best['pv'][0], 'move_uci': best['move'], 'confidence': 'engine_verified'}
    result['coach'] = coach_for(result['classification'], result['concepts'])
    knowledge = analyze_position(board, move, {"candidates": result['candidates']}, book=result.get('book'))
    if coach_context is not None:
        knowledge['coach_context'] = coach_context.update(
            ply=ply or board.ply() + 1, move=move.uci(), classification=result['classification'],
            knowledge=knowledge,
            coach_topic=(knowledge.get('coaching_topics') or [None])[0],
            warning=result['classification'] if result['classification'] in {'Mistake', 'Blunder', 'Miss'} else None)
    emma = compose_emma(classification=result['classification'], knowledge=knowledge,
                        evaluation=played, context=knowledge.get('coach_context') or {},
                        ply=ply)
    result['coach'] = emma
    result['intelligence'] = intelligence_result(
        ply=None, move_uci=move.uci(), move_san=san, fen_before=board.fen(), fen_after=child.fen(),
        evaluation_before=best, evaluation_after=played, best_move=best['move'],
        candidates=result['candidates'], loss_units=result['loss_units'],
        classification=result['classification'], forced_move=result['forced_move'],
        book=bool(result.get('book')), concepts=result['concepts'], threats=[],
        hint=result['hint'], coach=emma, knowledge=knowledge, preliminary=preliminary,
        verification_occurred=result['verification_occurred'], provenance=engine.provenance)
    return result


def run_review(game, moves, progress=lambda ply: None, publish=None, tiers=None, initial_result=None):
    """One engine per job. Publish each fast/deep ply without changing replay order.
    Search hash resets remain per common-root candidate for matched comparisons.
    """
    practice = game.get('mode') == 'practice'
    revision = game.get('analysis_revision', 1)
    rows = list((initial_result or {}).get('moves', []))
    start = time.monotonic()
    errors = []
    with Engine() as engine:
        def snapshot(stage, done):
            final = stage == 'complete'
            analyzed_count = sum(bool(r.get('classification')) for r in rows) if stage == 'fast_analysis' else sum(bool(r.get('authoritative')) for r in rows)
            white = measure([r for r in rows if r['color'] == 'white']) if final else None
            black = measure([r for r in rows if r['color'] == 'black']) if final else None
            white_v1 = game_accuracy([r for r in rows if r['color'] == 'white']) if final else None
            black_v1 = game_accuracy([r for r in rows if r['color'] == 'black']) if final else None
            return {'engine': engine.provenance['engine']['name'], 'settings': engine.provenance['settings'],
                'provenance': engine.provenance, 'model_version': C.MODEL_VERSION,
                'classifier_version': C.CLASSIFIER_VERSION, 'accuracy_model_version': C.ACCURACY_VERSION,
                'analysis_revision': revision, 'pipeline_version': 'progressive-v1', 'stage': stage,
                'analyzed_plies': analyzed_count, 'processed_plies': done, 'total_plies': len(moves),
                'percentage': round(100*analyzed_count/len(moves), 1) if moves else 100,
                'authoritative_plies': sum(bool(r.get('authoritative')) for r in rows),
                'accuracy_experimental': True,
                'white_accuracy': white['value'] if white else None,
                'black_accuracy': black['value'] if black else None,
                'white_bishoply_accuracy_v1': white_v1['value'] if white_v1 else None,
                'black_bishoply_accuracy_v1': black_v1['value'] if black_v1 else None,
                'accuracy_v1_model_version': 'bishoply-game-accuracy-v1-volatility',
                'accuracy_details': {'white': white, 'black': black}, 'moves': list(rows),
                'emma_summary': game_summary(context=coach_context.to_dict(), phase=(rows[-1].get('intelligence', {}).get('knowledge', {}).get('phase') if rows else None), game_id=game.get('public_id')) if final else None,
                'starting_fen': game['starting_fen'], 'hints_used': game.get('hint_count', 0),
                'mode': game.get('mode'), 'failed_plies': sorted(set(errors)),
                'analyzed_at': datetime.now(timezone.utc).isoformat(),
                'elapsed_seconds': round(time.monotonic()-start, 3)}
        # Preserve direct callers' authoritative-only benchmark/legacy contract.
        for preliminary in (tiers if tiers is not None else ((True, False) if publish else (False,))):
            coach_context = CoachContext()
            board = chess.Board(game['starting_fen'])
            stage = 'fast_analysis' if preliminary else 'deep_analysis'
            if publish: publish(snapshot(stage, 0))
            for index, row in enumerate(moves, 1):
                if time.monotonic()-start > 3600:
                    raise RuntimeError('Review work budget exceeded')
                move = chess.Move.from_uci(row['uci'])
                try:
                    analyzed = analyze_move(engine, board, move, practice=practice, revision=revision,
                        assisted=bool(row.get('assisted')), preliminary=preliminary,
                        coach_context=coach_context, ply=index)
                    analyzed['ply'] = index
                    if isinstance(analyzed.get('intelligence'), dict): analyzed['intelligence']['ply'] = index
                    if len(rows) < index: rows.append(analyzed)
                    else: rows[index-1] = analyzed
                    if index in errors: errors.remove(index)
                except (RuntimeError, ValueError):
                    if not publish: raise
                    errors.append(index)
                    if len(rows) < index:
                        rows.append({'ply': index, 'color': 'white' if board.turn else 'black',
                            'san': row['san'], 'fen': row['fen_after'], 'played_move': row['uci'],
                            'preliminary': True, 'authoritative': False, 'analysis_error': True})
                board.push(move)
                if board.fen() != row['fen_after']: raise ValueError('Stored move/FEN mismatch')
                progress(index)
                if publish: publish(snapshot(stage, index))
            if board.fen() != game['current_fen']: raise ValueError('Final FEN mismatch')
        return snapshot('deep_queued' if tiers == (True,) else 'failed' if errors else 'complete', len(moves))
