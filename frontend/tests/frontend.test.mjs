import assert from "node:assert/strict";
import { normalizeRoute } from "../web/router.js";
import { STARTING_FEN, createLabState, importLabFen, resetLab } from "../web/lab.js";

assert.deepEqual(normalizeRoute("/training/abc"), { page: "training", gameId: "abc" });
assert.equal(normalizeRoute("/shop").page, "shop");
const initial = createLabState();
assert.equal(initial.fen, STARTING_FEN);
assert.equal(importLabFen(initial, "bad").error.length > 0, true);
assert.equal(importLabFen(initial, STARTING_FEN).error, "");
assert.equal(resetLab({ ...initial, fen: STARTING_FEN.replace(" w ", " b ") }).fen, STARTING_FEN);
console.log("frontend tests: 6 passed");
