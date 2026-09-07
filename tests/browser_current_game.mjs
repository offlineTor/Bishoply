// Run isolated API: .venv/bin/python -m uvicorn tests.browser_server:app --port 8019
// Run Vite: cd frontend && npm run dev -- --host 127.0.0.1 --port 5179
// Install test-only Playwright outside the app: npm install --prefix /tmp/bishoply-ui-check playwright
// Run: node tests/browser_current_game.mjs
import assert from "node:assert/strict";
import fs from "node:fs/promises";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "/tmp/bishoply-ui-check/node_modules/playwright/index.mjs");
const browser = await chromium.launch({ channel: "chrome", headless: true });
const source = await fs.readFile("frontend/main.js", "utf8");
const errors = [];
const API = "http://127.0.0.1:8019";
const request = async (page, path, data) => {
  const response = await page.request.fetch(`${API}${path}`, { method: data ? "POST" : "GET", data });
  assert.ok(response.ok(), `${path}: ${await response.text()}`);
  return response.json();
};
async function setup(mobile = false) {
  const context = await browser.newContext({ viewport: mobile ? {width:390,height:844} : {width:1440,height:1100}, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: 1 });
  const page = await context.newPage();
  let engineRequests = 0;
  page.on("request",r => { if (/\/analysis(?:\?|$)/.test(r.url())) engineRequests++; });
  page.engineRequests = () => engineRequests;
  page.on("pageerror", error => errors.push(error.message));
  // Development HMR must not reload a fixture-injected module mid-test.
  await page.route("**/@vite/client", route => route.fulfill({contentType:"application/javascript",body:
    "export const createHotContext=()=>({accept(){},dispose(){},prune(){},on(){},send(){},invalidate(){}}); export const injectQuery=(url)=>url; export const updateStyle=()=>{}; export const removeStyle=()=>{};"}));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${API}${url.pathname}${url.search}` });
    await route.fulfill({ response });
  });
  await page.route("**/main.js*", route => route.fulfill({ contentType: "application/javascript", body: source
    .replace(/import \{ DiscordSDK \} from "@discord\/embedded-app-sdk";/, "class DiscordSDK {}")
    .replace(/setupBishoply\(\);\s*$/, `
      appReady = true;
      window.gameTest = {
        async enter(game, id = '101') { currentProfile = {discord_id:id}; showPage('game'); await renderGame(game); },
        sync: syncCurrentGame,
        state: () => ({fen: currentGame.fen, review: reviewPosition, circles: annotationCircles, arrows: annotationArrows, sound: chessSound.enabled}),
      };`) }));
  await page.goto("http://127.0.0.1:5179");
  await page.waitForFunction(() => !!window.gameTest);
  return { context, page };
}
try {
  const { page, context } = await setup();
  const game = await request(page, "/api/games/casual", {discord_id:101});
  await page.evaluate(game => gameTest.enter(game), game);
  await page.getByText("Your seat is ready").waitFor();
  assert.equal(await page.locator("#board .square").count(), 64);
  assert.equal(await page.locator("#game-review").isVisible(), false);
  assert.equal((await page.request.post(`${API}/api/games/${game.game_id}/analysis`)).status(), 409);
  await request(page, `/api/games/${game.game_id}/join`, {discord_id:202});
  await page.evaluate(() => gameTest.sync());
  await page.locator('#board [data-square="e2"]').click();
  assert.equal(await page.locator('#board [data-square="e4"].legal-target').count(), 1);
  assert.equal(await page.locator('#board [data-square="e2"].selected-square').count(), 1);
  await page.locator('#board [data-square="e4"]').click();
  await page.waitForFunction(() => gameTest.state().fen.startsWith("rnbqkbnr/pppppppp/8/8/4P3"));
  await request(page, `/api/games/${game.game_id}/move`, {discord_id:202,move:"e7e5"});
  await page.evaluate(() => gameTest.sync());
  await page.locator('#board [data-square="d4"]').click({button:"right"});
  assert.equal((await page.evaluate(() => gameTest.state())).circles.length, 1);
  const start = await page.locator('#board [data-square="d4"]').boundingBox();
  const end = await page.locator('#board [data-square="f6"]').boundingBox();
  await page.mouse.move(start.x + start.width/2, start.y + start.height/2);
  await page.mouse.down({button:"right"});
  await page.mouse.move(end.x + end.width/2, end.y + end.height/2, {steps:12});
  await page.mouse.up({button:"right"});
  assert.equal((await page.evaluate(() => gameTest.state())).arrows.length, 1);
  assert.equal(await page.locator(".annotation-layer svg").count(), 1);
  const board = await page.locator("#board").boundingBox();
  assert.ok(Math.abs(board.width-board.height)<1);
  await page.screenshot({path:"/tmp/bishoply-current-game-desktop.png",fullPage:true});
  await page.locator("#chess-sound-button").click();
  assert.equal(await page.evaluate(() => localStorage.getItem("bishoply.chess.sound")), "off");
  const blackGame = await request(page, `/api/games/${game.game_id}`);
  await page.evaluate(game => gameTest.enter(game, "202"), blackGame);
  assert.equal(await page.locator("#board .square").first().getAttribute("data-square"), "h1");
  await page.locator("#resign-game-button").click();
  // Existing two-click resignation confirmation stays functional.
  await page.locator("#resign-game-button").click();
  await page.locator('#game-result-dialog[open]').waitFor();
  assert.equal(await page.locator('#result-title').textContent(), 'Defeat');
  assert.equal(await page.locator('#result-reason').textContent(), 'You Resigned');
  assert.equal(await page.locator('#game-review').isVisible(), false);
  assert.equal((await request(page, `/api/games/${game.game_id}`)).status, "white_win");
  assert.equal(page.engineRequests(),0,"Results must not request or wait for analysis");
  // Review rendering fixture isolates UI from lengthy engine analysis; real engine is tested in Python.
  const result = {engine:"Stockfish 19", settings:{depth:20}, analyzed_at:new Date().toISOString(), white_accuracy:99,black_accuracy:98,
    moves:[{ply:1,move_number:1,color:"white",fen:blackGame.moves[0].fen_after,played_move:"e2e4",san:"e4",classification:"Best",white_outcome:.52,evaluation_after:{cp:20,mate:null},pv:["e4","e5"]}]};
  let response = {status:"queued",result:null};
  let requests = 0;
  await page.route(`**/api/games/${game.game_id}/analysis`, route => {requests++;return route.fulfill({json:response});});
  await page.locator("[data-result-review]").click();
  await page.locator("[data-begin]").click();
  await page.locator("[data-review-next]").click();
  assert.equal((await page.evaluate(() => gameTest.state())).review.fen, result.moves[0].fen);
  assert.equal(await page.locator("#match-mode-label").textContent(), "Post-game analysis · Replay");
  assert.equal(await page.locator(".game-side").isVisible(), false);
  response = {status:"fast_analysis", analyzed_plies:1,total_plies:2,result:{...result,moves:result.moves.map(m=>({...m,preliminary:true}))}};
  await page.getByText("Best · Preliminary",{exact:true}).waitFor();
  await page.getByText("Best continuation",{exact:true}).click();
  const selectedFen = (await page.evaluate(() => gameTest.state())).review.fen;
  response = {status:"complete", analyzed_plies:2,total_plies:2,result:{...result,moves:result.moves.map(m=>({...m,classification:"Excellent",authoritative:true}))}};
  await page.getByText("Analysis complete",{exact:true}).waitFor();
  assert.equal((await page.evaluate(() => gameTest.state())).review.fen,selectedFen);
  assert.equal(await page.locator('[data-review-detail="pv"]').getAttribute("open"), "");
  await page.locator("[data-flip]").click();
  assert.equal(await page.locator("#board .square").first().getAttribute("data-square"), "a8");
  await page.screenshot({path:"/tmp/bishoply-current-game-review.png",fullPage:true});
  await page.locator("[data-back-results]").click();
  assert.equal((await page.evaluate(() => gameTest.state())).review,null);
  await page.locator("[data-result-review]").click();
  await page.getByText("Analysis complete",{exact:true}).waitFor();
  assert.ok(requests >= 3);
  await page.locator("[data-back-results]").click();
  const variants = [
    ['white_win','checkmate','Victory','Won by Checkmate'],
    ['black_win','timeout','Defeat','Out of Time'],
    ['white_win','timeout','Victory','Won on Time'],
    ['draw','stalemate','Draw','Stalemate'],
    ['draw','threefold_repetition','Draw','Threefold Repetition'],
    ['draw','fifty_move_rule','Draw','Fifty-Move Rule'],
    ['draw','insufficient_material','Draw','Insufficient Material'],
    ['draw','draw_by_agreement','Draw','Draw by Agreement'],
  ];
  for (const [status,reason,title,subtitle] of variants) {
    await page.evaluate(g => gameTest.enter(g,'101'), {...blackGame,game_id:`fixture-${reason}-${status}`,status,termination_reason:reason,result:status==='draw'?'1/2-1/2':'1-0'});
    assert.equal(await page.locator('#result-title').textContent(),title);
    assert.equal(await page.locator('#result-reason').textContent(),subtitle);
    assert.equal(await page.locator('.ending-badge').allTextContents().then(x=>x.join(',')),status==='draw'?'Draw,Draw':'Winner,Loser');
  }
  await page.screenshot({path:"/tmp/bishoply-results-desktop.png",fullPage:true});
  await context.close();

  const mobile = await setup(true);
  const mobileGame = await request(mobile.page, "/api/games/casual", {discord_id:101});
  await request(mobile.page, `/api/games/${mobileGame.game_id}/join`, {discord_id:202});
  await mobile.page.evaluate(game => gameTest.enter(game), await request(mobile.page, `/api/games/${mobileGame.game_id}`));
  await mobile.page.locator('#board [data-square="e2"]').tap();
  assert.equal(await mobile.page.locator('#board [data-square="e4"].legal-target').count(), 1);
  await mobile.page.locator('#board [data-square="e4"]').tap();
  await mobile.page.waitForFunction(() => gameTest.state().fen.startsWith("rnbqkbnr/pppppppp/8/8/4P3"));
  const mobileBoard = await mobile.page.locator("#board").boundingBox();
  assert.ok(Math.abs(mobileBoard.width-mobileBoard.height)<1);
  assert.equal(await mobile.page.locator(".annotation-layer").count(), 0);
  assert.ok(await mobile.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await mobile.page.screenshot({path:"/tmp/bishoply-current-game-mobile.png",fullPage:true});
  await request(mobile.page, `/api/games/${mobileGame.game_id}/resign`, {discord_id:202});
  await mobile.page.evaluate(() => gameTest.sync());
  await mobile.page.locator('#game-result-dialog[open]').waitFor();
  assert.equal(await mobile.page.locator('#result-title').textContent(),'Victory');
  const modal=await mobile.page.locator('#game-result-dialog').boundingBox();
  assert.ok(modal.x>=0 && modal.x+modal.width<=390);
  assert.ok(modal.y>=0 && modal.y+modal.height<=844);
  await mobile.page.screenshot({path:"/tmp/bishoply-results-mobile.png",fullPage:true});
  await mobile.page.route(`**/api/games/${mobileGame.game_id}/analysis`,route=>route.fulfill({json:{status:'queued'}}));
  await mobile.page.locator('[data-result-review]').tap();
  await mobile.page.locator('[data-begin]').tap();
  await mobile.page.locator('[data-review-next]').tap();
  assert.ok((await mobile.page.evaluate(()=>gameTest.state())).review.fen);
  assert.ok(await mobile.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await mobile.page.screenshot({path:"/tmp/bishoply-review-mobile.png",fullPage:true});
  await mobile.context.close();
  assert.deepEqual(errors, []);
  console.log("PASS: board render/square sizing, click/tap moves, legal highlights, opponent sync, Black orientation, right-click circles/arrows, resign, mute preference, completed review/replay, mobile overflow, live review rejection; no browser errors.");
} finally {
  await browser.close();
}
