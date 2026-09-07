"""Optional genuine Polyglot book. No engine-derived or invented Book labels."""
import hashlib
import json
import os
from pathlib import Path
import chess.polyglot


def lookup(board, move):
    configured = os.getenv("BISHOPLY_POLYGLOT_BOOK")
    if not configured:
        return None
    path = Path(configured)
    with chess.polyglot.open_reader(str(path)) as reader:
        entries = [entry for entry in reader.find_all(board) if entry.move == move and entry.weight > 0]
    if not entries:
        return None
    metadata = {}
    sidecar = path.with_suffix(path.suffix + ".json")
    if sidecar.exists():
        metadata = json.loads(sidecar.read_text()).get(f"{chess.polyglot.zobrist_hash(board):016x}:{move.uci()}", {})
    return {"book_move": move.uci(), "book_source": path.name,
            "book_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "opening_name": metadata.get("opening_name"), "eco": metadata.get("eco"),
            "weight": max(entry.weight for entry in entries)}
