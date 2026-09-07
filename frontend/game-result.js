// One presentation policy for results, reasons, player panels and outcome sounds.
import { LAUNCH_FEATURES } from "./launch-config.js";
export const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
export const isCompleted = game => ["white_win", "black_win", "draw"].includes(game?.status);
export const isEnded = game => isCompleted(game) || ["aborted", "cancelled", "canceled"].includes(game?.status);
const REASONS = {
  checkmate: "Checkmate", resignation: "Resignation", timeout: "Out of Time", out_of_time: "Out of Time", time_forfeit: "Out of Time",
  stalemate: "Stalemate", threefold_repetition: "Threefold Repetition", repetition: "Threefold Repetition",
  fifty_move_rule: "Fifty-Move Rule", fifty_moves: "Fifty-Move Rule", fifty_move: "Fifty-Move Rule",
  insufficient_material: "Insufficient Material", draw_agreement: "Draw by Agreement", agreement: "Draw by Agreement", draw_by_agreement: "Draw by Agreement",
  seventyfive_move_rule: "75-Move Rule", seventyfive_moves: "75-Move Rule", fivefold_repetition: "Fivefold Repetition",
  aborted: "Game Aborted", cancelled: "Game Cancelled", canceled: "Game Cancelled",
};
export const formatTermination = reason => REASONS[String(reason || "").toLowerCase()] || "Game Complete";
export function resultSummary(game, myColor) {
  const winner = game.status === "white_win" ? "white" : game.status === "black_win" ? "black" : null;
  const outcome = game.status === "draw" ? "draw" : winner ? (myColor ? (winner === myColor ? "victory" : "defeat") : "complete") : "cancelled";
  const title = {draw:"Draw", victory:"Victory", defeat:"Defeat", complete:`${winner === "white" ? "White" : "Black"} Wins`, cancelled:game.status === "aborted" ? "Game Aborted" : "Game Cancelled"}[outcome];
  const reason = String(game.termination_reason || game.status).toLowerCase();
  let subtitle = formatTermination(reason);
  if (winner) {
    if (reason === "checkmate") subtitle = outcome === "defeat" ? "Lost by Checkmate" : "Won by Checkmate";
    if (reason === "resignation") subtitle = outcome === "defeat" ? "You Resigned" : outcome === "victory" ? "Opponent Resigned" : "Won by Resignation";
    if (["timeout","out_of_time","time_forfeit"].includes(reason)) subtitle = outcome === "defeat" ? "Out of Time" : "Won on Time";
  }
  return {winner, outcome, title, subtitle};
}
const number = n => Number(n).toLocaleString(undefined, {maximumFractionDigits:0});
const signed = n => `${Number(n) > 0 ? "+" : ""}${number(n)}`;
export function resultPlayer(game, color) {
  const player = game[color];
  const winner = resultSummary(game).winner;
  const badge = game.status === "draw" ? "Draw" : winner ? (color === winner ? "Winner" : "Loser") : color;
  const snapshot = game.competitive?.[color];
  const approved = game.competitive?.decision === "approved";
  const rating = snapshot?.rating_after ?? player?.chess_rating ?? game.rating?.[`${color}_before`];
  const sr = snapshot?.sr_after ?? player?.sr;
  const stat = (label, key, value) => `<div class="ending-stat"><span>${label}</span><strong>${approved && snapshot?.[`${key}_before`] != null && snapshot?.[`${key}_after`] != null ? `${number(snapshot[`${key}_before`])} → ${number(snapshot[`${key}_after`])}` : value != null ? number(value) : "—"}</strong>${approved && snapshot?.[`${key}_change`] != null ? `<em>${signed(snapshot[`${key}_change`])}</em>` : ""}</div>`;
  let avatar = "";
  try { const url = new URL(player?.avatar_url); if (url.protocol === "https:") avatar = `<img src="${escape(url.href)}" alt="" referrerpolicy="no-referrer">`; } catch {}
  return `<article class="ending-player ${color === winner ? "winner" : ""}"><span class="ending-badge">${badge}</span><div class="player-avatar">${avatar || (color === "white" ? "♙" : "♟")}</div><h3>${escape(player?.display_name || player?.username || color)}</h3>${stat("Bishoply Chess Rating","rating",rating)}${sr != null ? stat("Bishoply SR","sr",sr) : ""}</article>`;
}
export class GameResult {
  constructor(dialog, onReview) {
    this.dialog = dialog;
    this.onReview = onReview;
    this.seen = new Set();
    dialog.addEventListener("click", event => {
      if (event.target.closest('[data-result-close]')) dialog.close();
      if (event.target.closest('[data-result-review]')) {
        dialog.close();
        (this.reviewHandler || this.onReview)?.();
      }
    });
  }
  load(game, color, onReview = null) {
    this.game = game; this.color = color;
    this.reviewHandler = onReview || this.onReview;
    if (!isEnded(game)) { if (this.dialog.open) this.dialog.close(); return; }
    if (!this.seen.has(game.game_id)) { this.seen.add(game.game_id); this.open(); }
    else if (this.dialog.open) this.render(); // Rating/SR updates are independent of Stockfish.
  }
  open() { this.render(); if (!this.dialog.open) this.dialog.showModal(); }
  render() {
    const g = this.game;
    if (!isEnded(g)) return;
    const {winner,title,subtitle} = resultSummary(g,this.color);
    const order = winner ? [winner,winner === "white" ? "black" : "white"] : ["white","black"];
    const decision = g.competitive?.decision || g.integrity_status;
    const processing = !g.rating_processed && g.rated_eligible && (!decision || decision === "pending");
    this.dialog.innerHTML = `<div class="ending-content"><span class="eyebrow gold">Match complete</span><h2 id="result-title">${title}</h2><p id="result-reason">${subtitle}</p><div class="ending-players">${order.map(c => resultPlayer(g,c)).join("")}</div><p class="ending-mode">${decision === "approved" ? "Rated" : processing ? "Rating / SR processing…" : "Unrated"}</p><div class="ending-actions">${isCompleted(g) && LAUNCH_FEATURES.gameReview ? '<button type="button" class="gold-button" data-result-review>Review Game</button>' : ""}<button type="button" class="dark-button" data-result-close autofocus>Close</button></div></div>`;
  }
}
