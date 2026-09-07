import assert from "node:assert/strict";
import {formatTermination,resultSummary,resultPlayer,isEnded} from "../frontend/game-result.js";
const reasons={checkmate:"Checkmate",resignation:"Resignation",timeout:"Out of Time",stalemate:"Stalemate",threefold_repetition:"Threefold Repetition",fifty_move_rule:"Fifty-Move Rule",insufficient_material:"Insufficient Material",draw_by_agreement:"Draw by Agreement",aborted:"Game Aborted",cancelled:"Game Cancelled",fivefold_repetition:"Fivefold Repetition",seventyfive_moves:"75-Move Rule"};
for (const [reason,label] of Object.entries(reasons)) assert.equal(formatTermination(reason),label);
assert.equal(formatTermination("unrecognized_private_enum"),"Game Complete");
for (const winner of ["white","black"]) {
  const game={status:`${winner}_win`,termination_reason:"checkmate"};
  assert.equal(resultSummary(game,winner).title,"Victory");
  assert.equal(resultSummary(game,winner === "white" ? "black" : "white").title,"Defeat");
  assert.ok(resultPlayer(game,winner).includes("Winner"));
}
assert.equal(resultSummary({status:"draw",termination_reason:"stalemate"}).title,"Draw");
assert.equal(resultSummary({status:"aborted"}).title,"Game Aborted");
assert.ok(isEnded({status:"cancelled"}));
const game={status:"white_win",termination_reason:"resignation",competitive:{decision:"approved",white:{rating_before:1500,rating_after:1518,rating_change:18,sr_before:2500,sr_after:2551,sr_change:51}},white:{display_name:"<script>",sr:2551}};
assert.ok(resultPlayer(game,"white").includes("1,500 → 1,518"));
assert.ok(resultPlayer(game,"white").includes("+51"));
assert.ok(resultPlayer(game,"white").includes("&lt;script&gt;"));
console.log("PASS: centralized reasons, winner/loser/draw/abort, rating/SR updates and escaping");
const {ChessSound}=await import('../frontend/chess-sound.js');
const played=[];
for (const [status,color,kind] of [['white_win','white','victory'],['white_win','black','defeat'],['draw','white','draw']]) {
  ChessSound.prototype.transition.call({play:s=>played.push(s)},{game_id:'g',status:'active'},{game_id:'g',status,termination_reason:'checkmate'},color);
  assert.equal(played.at(-1),kind);
}
const count=played.length;
ChessSound.prototype.transition.call({play:s=>played.push(s)},null,{game_id:'g',status:'white_win'},'white');
assert.equal(played.length,count,'Historical loads must not replay result audio');
console.log('PASS: distinct victory/defeat/draw sound routing; no result audio on initial loads');
