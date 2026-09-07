"""One Bishoply classifier for both modes. Every special award retains evidence."""
from . import config as C

VERSION = C.MODEL_VERSION
CATEGORIES = C.CATEGORIES


def normal_quality(loss_units):
    if type(loss_units) is not int or not 0 <= loss_units <= 2000:
        raise ValueError('Opportunity loss must be an integer in [0,2000]')
    return next((label for upper, label in C.THRESHOLDS if loss_units <= upper), 'Blunder')


def draw_policy(board):
    outcome = board.outcome(claim_draw=False)
    return {'terminal': outcome.termination.name.lower() if outcome else None,
            'claimable_repetition': board.can_claim_threefold_repetition(),
            'claimable_fifty_moves': board.can_claim_fifty_moves(),
            'policy': 'automatic terminals are exact; claimable draws are recorded, not silently claimed'}


def mate_policy(best, played, child):
    b, p = best.get('mate'), played.get('mate')
    transition = None
    if child.is_checkmate():
        transition = 'terminal_checkmate'
    elif b is not None and b > 0:
        if p is None or p <= 0:
            transition = 'lost'
        else:
            transition = 'shortened' if p < b else 'lengthened' if p > b else 'preserved'
    elif p is not None and p > 0:
        transition = 'discovered'
    elif b is not None and b < 0 and (p is None or p >= 0):
        transition = 'escaped'
    elif p is not None and p < 0:
        transition = 'forced_loss'
    return {'transition': transition, 'best_mate': b, 'played_mate': p,
            'distance_policy': 'prefer shorter winning mates; do not penalize sound longer mates solely for distance'}


def classify_move(board, move, candidates, *, verified=False, stable=False, practice=False, book=None):
    best = candidates[0]
    played = next(c for c in candidates if c['move'] == move.uci())
    forced = board.legal_moves.count() == 1
    loss = 0 if forced else max(0, best['outcome_units'] - played['outcome_units'])
    child = board.copy()
    child.push(move)
    mate = mate_policy(best, played, child)
    evidence = {'best_candidate': best, 'second_best_candidate': candidates[1] if len(candidates) > 1 else None,
                'verified_outcome_difference_units': best['outcome_units'] - candidates[1]['outcome_units'] if len(candidates) > 1 else 0}
    label = normal_quality(loss)
    if forced:
        label = 'Forced'
    elif book and practice:
        label = 'Book'
    elif verified and stable:
        missed_mate = mate['transition'] == 'lost'
        missed_gain = (best.get('material_gain', 0) >= C.MATERIAL_GAIN and
                       best.get('material_gain', 0) - played.get('material_gain', 0) >= C.MATERIAL_GAIN and
                       best['outcome_units'] >= C.NONWINNING_CEILING and loss >= C.MISS_GAP)
        if missed_mate or missed_gain:
            label = 'Miss'
            evidence['missed_opportunity'] = {'type': 'forced_mate' if missed_mate else 'major_material_win',
                'best_move': best['move'], 'pv': best['pv'], 'material_gain': best.get('material_gain'),
                'opportunity_loss_units': loss}
    return {'classification': label, 'loss_units': loss, 'loss': loss / 2000,
            'forced_move': forced, 'forced_tactical': board.is_check(), 'mate_policy': mate,
            'draw_policy': draw_policy(child), 'book': book,
            'evidence': evidence, 'experimental': label == 'Miss'}
