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
