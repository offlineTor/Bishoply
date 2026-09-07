"""Conservative, evidence-backed chess concept extraction."""
import chess

def extract(board: chess.Board, move: chess.Move, *, material_delta: int = 0) -> list[dict]:
    concepts = []
    if board.gives_check(move): concepts.append({'topic': 'check', 'evidence': move.uci()})
    if board.is_capture(move): concepts.append({'topic': 'capture', 'evidence': move.uci()})
    if move.promotion: concepts.append({'topic': 'promotion', 'evidence': move.uci()})
    if board.is_castling(move): concepts.append({'topic': 'castling', 'evidence': move.uci()})
    if material_delta > 0: concepts.append({'topic': 'material_gain', 'value': material_delta, 'evidence': move.uci()})
    elif material_delta < 0: concepts.append({'topic': 'material_loss', 'value': abs(material_delta), 'evidence': move.uci()})
    if chess.square_file(move.to_square) in (3, 4) and chess.square_rank(move.to_square) in (3, 4):
        concepts.append({'topic': 'center_occupation', 'evidence': chess.square_name(move.to_square)})
    piece = board.piece_at(move.from_square)
    if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP) and board.fullmove_number <= 12:
        concepts.append({'topic': 'development', 'evidence': move.uci()})
    return concepts

def coach_for(classification: str, concepts: list[dict]) -> dict:
    topics = {item['topic'] for item in concepts}
    if classification in {'Blunder', 'Mistake', 'Miss'}:
        message = {'Blunder': 'Careful. This allows a major tactical swing.', 'Mistake': 'Careful. This changes the position significantly.', 'Miss': 'There was a stronger verified opportunity here.'}[classification]
        priority = 'high'
    elif 'check' in topics: message, priority = 'That check creates an immediate forcing move.', 'high'
    elif 'development' in topics and 'center_occupation' in topics: message, priority = 'Nice. This develops a piece and contests the center.', 'normal'
    elif 'center_occupation' in topics: message, priority = 'This move claims useful space in the center.', 'low'
    elif classification in {'Best', 'Excellent'}: message, priority = 'Strong choice. This keeps the position healthy.', 'normal'
    else: message, priority = None, 'low'
    return {'should_comment': bool(message), 'should_speak': priority == 'high', 'priority': priority,
            'topic': next(iter(topics), 'move'), 'message': message, 'supporting_facts': concepts}
