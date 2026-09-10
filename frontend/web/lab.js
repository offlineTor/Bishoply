/** Pure, unrated Bishoply Lab position state. Nothing here touches Practice or games. */
export const LAB_MODES = Object.freeze(["free", "analyze", "play", "bot-white", "bot-black"]);
export const STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

export function validateFen(fen) {
  const parts = String(fen || "").trim().split(/\s+/);
  if (parts.length !== 6 || parts[0].split("/").length !== 8 || !/^[wb]$/.test(parts[1])) throw new Error("Enter a valid six-field FEN position.");
  for (const rank of parts[0].split("/")) {
    let count = 0;
    for (const ch of rank) count += /[1-8]/.test(ch) ? Number(ch) : /[prnbqkPRNBQK]/.test(ch) ? 1 : 99;
    if (count !== 8) throw new Error("Each FEN rank must contain eight squares.");
  }
  return parts.join(" ");
}

export function createLabState(fen = STARTING_FEN) { return { mode: "free", fen: validateFen(fen), flipped: false, error: "" }; }
export function importLabFen(state, fen) { try { return { ...state, fen: validateFen(fen), error: "" }; } catch (error) { return { ...state, error: error.message }; } }
export function resetLab(state) { return { ...state, fen: STARTING_FEN, error: "" }; }

export function editFen(state, square, piece = "") {
  const parts = state.fen.split(" "); const ranks = parts[0].split("/");
  const file = square.charCodeAt(0) - 97, rank = 8 - Number(square[1]);
  if (file < 0 || file > 7 || rank < 0 || rank > 7 || !/^[a-h][1-8]$/.test(square)) return { ...state, error: "Choose a valid board square." };
  const expanded = ranks.map(row => [...row].flatMap(ch => /[1-8]/.test(ch) ? Array(Number(ch)).fill("") : [ch]));
  expanded[rank][file] = piece;
  const board = expanded.map(row => { let out="", empty=0; for (const ch of row) { if (!ch) empty++; else { if (empty) out += empty; empty=0; out += ch; } } return out + (empty || ""); }).join("/");
  return { ...state, fen: [board, ...parts.slice(1)].join(" "), error: "" };
}

export function clearLabBoard(state) { return editFen({ ...state, fen: `8/8/8/8/8/8/8/8 ${state.fen.split(" ").slice(1).join(" ")}` }, "a1", ""); }

export function boardPieces(fen) {
  const rows = fen.split(" ")[0].split("/"); const result = {};
  rows.forEach((row, r) => { let file=0; for (const ch of row) { if (/\d/.test(ch)) file += Number(ch); else { result[`${String.fromCharCode(97+file)}${8-r}`] = ch; file++; } } });
  return result;
}
