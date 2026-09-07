// Run Vite: cd frontend && npm run dev -- --host 127.0.0.1 --port 5179
// Install test-only Playwright outside the app: npm install --prefix /tmp/bishoply-ui-check playwright
// Run: node tests/browser_practice.mjs
import assert from "node:assert/strict";
import fs from "node:fs/promises";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "/tmp/bishoply-ui-check/node_modules/playwright/index.mjs");
const browser = await chromium.launch({ headless: true });
const source = await fs.readFile("frontend/main.js", "utf8");
const errors = [];
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";
const E5_FEN = "rnbqkbnr/pppppppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2";

const bots = [
  ["scout", "Scout", 600, "Beginner", "Forgiving; reasonable lower-ranked moves"],
  ["tempo", "Tempo", 800, "Casual", "Natural development; occasional tactical misses"],
  ["fork", "Fork", 1000, "Developing", "Knight tactics, with bounded inconsistency"],
  ["gambit", "Gambit", 1200, "Club Player", "Active play and attacking chances"],
  ["castle", "Castle", 1400, "Strong Club", "King safety and positional restraint"],
  ["tactician", "Tactician", 1600, "Tournament Player", "Checks, captures and tactical lines"],
  ["endgame", "Endgame", 1800, "Expert", "Increasing precision as material decreases"],
  ["vanguard", "Vanguard", 2000, "Advanced / Master Strength", "Balanced strong play"],
  ["maestro", "Maestro", 2200, "Elite", "Strong play with restrained stylistic variety"],
  ["crown", "Crown", 2400, "Grandmaster Strength", "Strongest normal Bishoply engine behavior"],
].map(([bot_id, display_name, estimated_strength, community_level, personality]) => ({
  bot_id,
  display_name,
  estimated_strength,
  community_level,
  personality,
  icon_path: `/assets/bots/${bot_id}.png`,
  calibration_version: "bishoply-bots-v1-experimental",
  strength_label: "Estimated Bot Strength",
  experimental: true,
}));

function createPracticeState(botId = "gambit", playerColor = "white") {
  const bot = bots.find(entry => entry.bot_id === botId) || bots[0];
  return {
    game_id: "practice_test_1",
    mode: "practice",
    unrated: true,
    player_color: playerColor,
    owner_discord_id: "101",
    bot,
    status: "active",
    result: null,
    termination_reason: null,
    fen: START_FEN,
    current_fen: START_FEN,
    ply: 0,
    turn: "white",
    needs_bot_move: playerColor === "black",
    busy: false,
    bot_error: null,
    hint_count: 0,
    assisted: false,
    hint_ply: -1,
    hint_stage: 0,
    hint_result: null,
    legal_moves: playerColor === "white"
      ? [{ uci: "e2e4", from: "e2", to: "e4", promotion: null }]
      : [],
    moves: [],
    starting_fen: START_FEN,
    bot_id: bot.bot_id,
    bot_strength: bot.estimated_strength,
    bot_personality: bot.personality,
    bot_config: bot,
    created_at: "2026-09-07T12:00:00Z",
    completed_at: null,
  };
}

function decoratedReviewMoves() {
  return [
    {
      ply: 1,
      move_number: 1,
      color: "white",
      actor: "player",
      uci: "e2e4",
      san: "e4",
      fen_after: E4_FEN,
      played_move: "e2e4",
      classification: "Best",
      preliminary: false,
      authoritative: true,
      evaluation_before: { cp: 0 },
      evaluation_after: { cp: 24 },
      white_outcome: 0.56,
      pv: ["e4", "e5"],
    },
    {
      ply: 2,
      move_number: 1,
      color: "black",
      actor: "bot",
      uci: "e7e5",
      san: "e5",
      fen_after: E5_FEN,
      played_move: "e7e5",
      classification: "Best",
      preliminary: false,
      authoritative: true,
      evaluation_before: { cp: 0 },
      evaluation_after: { cp: 0 },
      white_outcome: 0.50,
      pv: ["e5", "Nf3"],
    },
  ];
}

async function setup() {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, isMobile: false, hasTouch: false, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const state = {
    practice: null,
    analysisCalls: new Map(),
  };

  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/@vite/client", route => route.fulfill({ contentType: "application/javascript", body:
    "export const createHotContext=()=>({accept(){},dispose(){},prune(){},on(){},send(){},invalidate(){}}); export const injectQuery=(url)=>url; export const updateStyle=()=>{}; export const removeStyle=()=>{};" }));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();

    if (pathname === "/api/practice/bots" && method === "GET") {
      return route.fulfill({ json: { strength_label: "Estimated Bot Strength", calibration_version: "bishoply-bots-v1-experimental", bots } });
    }

    if (pathname === "/api/practice/games" && method === "POST") {
      const payload = JSON.parse(route.request().postData() || "{}");
      state.practice = createPracticeState(payload.bot_id || "gambit", payload.player_color || "white");
      return route.fulfill({ json: { ...state.practice, access_key: "practice-test-key" } });
    }

    const gameMatch = pathname.match(/^\/api\/practice\/games\/([^/]+)(?:\/(move|bot-move|hint|resign|review|analysis\/(\d+)))?$/);
    if (gameMatch) {
      const gameId = gameMatch[1];
      const action = gameMatch[2] || "";
      const ply = Number(gameMatch[3] || 0);
      if (!state.practice || state.practice.game_id !== gameId) {
        return route.fulfill({ status: 404, json: { detail: "Practice game not found" } });
      }

      if (method === "GET" && action === "") {
        return route.fulfill({ json: state.practice });
      }

      if (method === "POST" && action === "move") {
        const payload = JSON.parse(route.request().postData() || "{}");
        assert.equal(payload.move, "e2e4");
        state.practice = {
          ...state.practice,
          fen: E4_FEN,
          current_fen: E4_FEN,
          ply: 1,
          turn: "black",
          needs_bot_move: true,
          legal_moves: [],
          moves: [{
            ply: 1,
            move_number: 1,
            color: "white",
            actor: "player",
            uci: "e2e4",
            san: "e4",
            fen_after: E4_FEN,
            assisted: false,
            hint_count: 0,
          }],
        };
        state.analysisCalls.set(1, 0);
        return route.fulfill({ json: { ...state.practice, analysis: { status: "queued", ply: 1 } } });
      }

      if (method === "POST" && action === "bot-move") {
        state.practice = {
          ...state.practice,
          fen: E5_FEN,
          current_fen: E5_FEN,
          ply: 2,
          turn: "white",
          needs_bot_move: false,
          legal_moves: [{ uci: "g1f3", from: "g1", to: "f3", promotion: null }],
          moves: [
            ...state.practice.moves,
            {
              ply: 2,
              move_number: 1,
              color: "black",
              actor: "bot",
              uci: "e7e5",
              san: "e5",
              fen_after: E5_FEN,
              assisted: false,
              hint_count: 0,
            },
          ],
        };
        return route.fulfill({ json: state.practice });
      }

      if (method === "POST" && action === "hint") {
        const payload = JSON.parse(route.request().postData() || "{}");
        const stage = Number(payload.stage || 1);
        state.practice = {
          ...state.practice,
          hint_count: stage,
          assisted: true,
          hint_stage: stage,
          hint_ply: state.practice.ply,
          hint_result: JSON.stringify({ stage }),
        };
        const hint = stage === 1
          ? { stage, piece_square: "e2" }
          : stage === 2
            ? { stage, piece_square: "e2", destination: "e4" }
            : { stage, piece_square: "e2", destination: "e4", recommended_move: "e2e4", san: "e4" };
        return route.fulfill({ json: hint });
      }

      if (method === "POST" && action === "resign") {
        state.practice = {
          ...state.practice,
          status: "black_win",
          result: "0-1",
          termination_reason: "resignation",
          completed_at: "2026-09-07T12:10:00Z",
        };
        return route.fulfill({ json: state.practice });
      }

      if (action.startsWith("analysis/")) {
        const current = state.analysisCalls.get(ply) || 0;
        state.analysisCalls.set(ply, current + 1);
        if (current === 0) {
          return route.fulfill({ json: { status: "queued", progress: 0, analysis_revision: 1, result: null, analyzed_plies: 0, total_plies: 1, percentage: 0 } });
        }
        return route.fulfill({
          json: {
            status: "complete",
            progress: 1,
            analysis_revision: 1,
            analyzed_plies: 1,
            total_plies: 1,
            percentage: 100,
            result: {
              stage: "complete",
              pipeline_version: "progressive-v1",
              engine: "Stockfish 19",
              settings: { depth: 20 },
              elapsed_seconds: 0.4,
              white_accuracy: 95.4,
              black_accuracy: 94.7,
              moves: [
                {
                  ply: 1,
                  move_number: 1,
                  color: "white",
                  actor: "player",
                  uci: "e2e4",
                  san: "e4",
                  fen: E4_FEN,
                  played_move: "e2e4",
                  classification: "Best",
                  preliminary: false,
                  authoritative: true,
                  evaluation_before: { cp: 0 },
                  evaluation_after: { cp: 24 },
                  white_outcome: 0.56,
                  pv: ["e4", "e5"],
                },
              ],
            },
          },
        });
      }

      if (method === "GET" && action === "review") {
        return route.fulfill({
          json: {
            status: "complete",
            progress: 2,
            analysis_revision: 1,
            analyzed_plies: 2,
            total_plies: 2,
            percentage: 100,
            result: {
              stage: "complete",
              pipeline_version: "progressive-v1",
              engine: "Stockfish 19",
              settings: { depth: 20 },
              elapsed_seconds: 1.1,
              white_accuracy: 95.4,
              black_accuracy: 94.7,
              moves: decoratedReviewMoves(),
            },
          },
        });
      }

      if (method === "POST" && action === "review") {
        return route.fulfill({ json: { status: "queued", progress: 0, analysis_revision: 1, result: null, analyzed_plies: 0, total_plies: 2, percentage: 0 } });
      }
    }

    return route.fulfill({ status: 404, json: { detail: `Unhandled ${method} ${pathname}` } });
  });

  await page.route("**/main.js*", route => route.fulfill({ contentType: "application/javascript", body: source
    .replace(/import \{ DiscordSDK \} from "@discord\/embedded-app-sdk";/, "class DiscordSDK {}")
    .replace(/setupBishoply\(\);\s*$/, `
      appReady = true;
      discordAccessToken = "practice-test-token";
      currentProfile = { discord_id: 101, username: "alex", display_name: "Alex Morgan", avatar_url: "https://cdn.discordapp.com/avatars/101/practice.png", rating: 1500, sr: 2500 };
      renderProfile(currentProfile);
      setControlsEnabled(true);
      renderEmptyGame();
      renderPracticeShell();
      await loadPracticeBots();
      window.practiceTest = {
        state: () => ({
          game: practiceGame,
          review: practiceReviewPosition,
          evalVisible: practiceEvalVisible,
          feedback: practiceAnalysisState,
          hint: practiceHintState,
        }),
      };
    `) }));

  await page.goto("http://127.0.0.1:5179");
  await page.waitForFunction(() => !!window.practiceTest);
  return { page, context };
}

try {
  const { page, context } = await setup();

  await page.getByText("Gambit").scrollIntoViewIfNeeded();
  await page.getByText("Start Practice", { exact: false }).first().click();
  await page.getByText("Practice started against Gambit.").waitFor();
  assert.equal(await page.locator(".practice-bot-card").count(), 10);
  assert.equal(await page.locator("#practice-board .square").count(), 64);
  assert.equal(await page.locator("#practice-eval-bar").isVisible(), true);
  await page.locator('#practice-board [data-square="e2"]').click();
  assert.equal(await page.locator('#practice-board [data-square="e4"].legal-target').count(), 1);
  await page.locator('#practice-board [data-square="e4"]').click();
  await page.getByText("Your move", { exact: false }).waitFor();
  await page.getByText("Best", { exact: false }).waitFor();
  await page.locator("#practice-eval-toggle").click();
  assert.equal(await page.locator("#practice-eval-bar").isVisible(), false);
  await page.locator("#practice-eval-toggle").click();
  assert.equal(await page.locator("#practice-eval-bar").isVisible(), true);
  await page.locator("#practice-hint-button").click();
  await page.locator("#practice-hint-button").click();
  await page.locator("#practice-hint-button").click();
  await page.getByText("Hints Used").waitFor();
  assert.equal(await page.locator(".practice-assisted").textContent(), "Assisted");
  await page.locator("#practice-resign-button").click();
  await page.locator('#game-result-dialog[open]').waitFor();
  await page.getByText("Defeat", { exact: true }).waitFor();
  await page.getByText("Review Game", { exact: true }).click();
  await page.getByText("Practice Review", { exact: false }).waitFor();
  await page.getByText("Hints Used", { exact: false }).waitFor();
  await page.getByText("Best", { exact: false }).waitFor();
  await page.screenshot({ path: "/tmp/bishoply-practice-desktop.png", fullPage: true });

  await context.close();
  assert.deepEqual(errors, []);
  console.log("PASS: Practice landing, game creation, click-to-move, bot response, live feedback, hints, eval toggle, resign, review navigation, desktop layout, and browser errors.");
} finally {
  await browser.close();
}
