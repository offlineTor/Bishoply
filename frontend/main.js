import { ChessSound } from "./chess-sound.js";
import { EmmaVoiceManager } from "./emma-voice.js";
import { LAUNCH_FEATURES } from "./launch-config.js";
import { GameResult, formatTermination, isEnded } from "./game-result.js";
import { GameReview } from "./game-review.js";
import { classificationUi, classificationBadge } from "./classification-ui.js";
import { DiscordSDK } from "./discord/client.js";
import { createApiTransport } from "./shared/api-transport.js";
import { isDiscordRuntime } from "./shared/runtime.js";

const CLIENT_ID = "1546225609967935620";
// The Embedded App SDK requires Discord-injected query parameters at
// construction time. Direct browser visits do not have them, so defer SDK
// creation until we have positively identified an Activity context.
const isDiscordActivity = isDiscordRuntime;
let discordSdk = null;

const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || "").replace(/\/$/, "");
const apiTransport = createApiTransport();

function backendRequestUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  // Discord's Activity mapping uses /api as a proxy prefix and strips it
  // before forwarding. The backend's application routes retain their /api
  // prefix, so an app request such as /api/auth/discord must be sent through
  // the proxy as /api/api/auth/discord. Health is the one backend route at
  // the root, so /health is sent as /api/health.
  return apiTransport.url(normalized);
}

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const statusElement = $("#status");
const connectionLabel = $("#connection-label");
const sidebarProfile = $("#sidebar-profile");

const sdkCheck = $("#sdk-check");
const apiCheck = $("#api-check");
const profileCheck = $("#profile-check");
const appSplash = $("#app-splash");
const webAuthScreen = $("#web-auth-screen");

const homeRating = $("#home-rating");
const homeRank = $("#home-rank");
const homeGames = $("#home-games");
const homeWinRate = $("#home-win-rate");

const createGameButton = $("#create-game-button");
const joinGameInput = $("#join-game-input");
const joinGameButton = $("#join-game-button");

const gameInfo = $("#game-info");
const boardElement = $("#board");
const movesList = $("#moves-list");
const practicePage = $("#page-practice");
const practiceLanding = $("#practice-landing");
const practiceLoading = $("#practice-loading");
const practiceLoadingBot = $("#practice-loading-bot");
const practiceLoadingStrength = $("#practice-loading-strength");
const practiceLoadingCopy = $("#practice-loading-copy");
const practiceBots = $("#practice-bots");
const practiceSession = $("#practice-session");
const practiceModeLabel = $("#practice-mode-label");
const practiceBoardElement = $("#practice-board");
const practicePlayerTop = $("#practice-player-top");
const practicePlayerBottom = $("#practice-player-bottom");
const practiceInfo = $("#practice-info");
const practiceMovesList = $("#practice-moves");
const practiceFeedback = $("#practice-feedback");
const practiceAnalysisCard = $("#practice-analysis-card");
const practiceSoundButton = $("#practice-sound-button");
const practiceEvalToggle = $("#practice-eval-toggle");
const practiceEvalBar = $("#practice-eval-bar");
const practiceEvalFill = $("#practice-eval-fill");
const practiceEvalValue = $("#practice-eval-value");
const practiceHintButton = $("#practice-hint-button");
const practiceBestButton = $("#practice-best-button");
const practiceWhyButton = $("#practice-why-button");
const practiceThreatButton = $("#practice-threat-button");
const practiceSpeakButton = $("#practice-speak-button");
const practiceEmmaVoiceButton = $("#practice-emma-voice-button");
const practiceCandidates = $("#practice-candidates");
const practiceResignButton = $("#practice-resign-button");
const practiceUndoButton = $("#practice-undo-button");
const matchmakingStatus = $("#matchmaking-status");
const cancelMatchmakingButton = $("#cancel-matchmaking-button");
const practiceRestartButton = $("#practice-restart-button");
const practiceNewOpponentButton = $("#practice-new-opponent-button");
const practiceCreateForm = $("#practice-create-form");
const practiceStatusLine = $("#practice-status-line");

const moveInput = $("#move-input");
const moveButton = $("#move-button");

const refreshHistoryButton = $("#refresh-history-button");
const historyList = $("#history-list");
const profilePageCard = $("#profile-page-card");
const accountLogoutButton = $("#account-logout-button");
const accountConnections = $("#account-connections");
const leaderboardList = $("#leaderboard-list");
const leaderboardRatingTab = $("#leaderboard-rating-tab");
const leaderboardSrTab = $("#leaderboard-sr-tab");
let leaderboardKind = "rating";


let currentProfile = null;
let profileCosmetics = { owned: [], loadout: {} };
let discordAccessToken = null;
let webSessionAuthenticated = false;
let currentGame = null;
let reviewPosition = null;
let reviewFlipped = false;
let practiceGame = null;
let practiceAccessKey = null;

function practiceAuthHeaders(headers = {}) {
  return practiceAccessKey ? { ...headers, "X-Practice-Key": practiceAccessKey } : headers;
}

function canAccessPracticeGame() {
  return Boolean(practiceAccessKey || currentProfile);
}
let practiceReviewPosition = null;
let practiceReviewFlipped = false;
let practiceSelectedSquare = null;
let practiceBoardPieces = {};
let practiceLegalMoves = [];
let practiceCanMove = false;
let practicePlayerColor = "white";
let practiceBusy = false;
let practiceBotBusy = false;
let matchmakingTimer = null;
let matchmakingPolling = false;
let practiceEvalVisible = true;
let practiceBotRoster = [];
let practiceAnalysisState = { status: "idle", message: "Analysis pending", classification: null };
let practiceHintState = null;
let practiceSuggestionState = null;
let practiceMoveAnalysis = new Map();
let practiceAnnouncedPly = null;
let practicePendingAnalysis = null;
let practiceAnalysisTimer = null;
let practiceLoadBusy = false;
let practiceChoice = { bot_id: null, player_color: "white" };
let practiceView = "select";
let practiceSpokenKey = null;
const practiceSpokenKeys = new Set();
let practiceCreateBusy = false;
const coachFeatures = Object.freeze({ hints: true, advancedCoach: false });
const chessSound = new ChessSound([$("#chess-sound-button"), practiceSoundButton]);
const emmaVoice = new EmmaVoiceManager({
  remoteSpeak: async text => {
    const response = await fetch(backendRequestUrl("/api/voice/speak"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!response.ok) throw new Error(`Emma voice service unavailable (${response.status})`);
    const audio = new Audio(URL.createObjectURL(await response.blob()));
    audio.addEventListener("ended", () => URL.revokeObjectURL(audio.src), { once: true });
    return audio;
  },
});
emmaVoice.onEvent = event => {
  if (import.meta.env?.DEV) console.debug("[Bishoply Emma Voice]", event);
};

function renderPracticeView(next = practiceView) {
  const previousView = practiceView;
  const allowed = new Set(["select", "loading", "match"]);
  practiceView = allowed.has(next) ? next : "select";
  const visible = {
    select: practiceView === "select",
    loading: practiceView === "loading",
    match: practiceView === "match",
  };
  if (practiceLanding) practiceLanding.hidden = !visible.select;
  if (practiceLoading) practiceLoading.hidden = !visible.loading;
  if (practiceSession) {
    practiceSession.hidden = !visible.match;
    practiceSession.classList.toggle("practice-active", visible.match);
  }
  practicePage?.classList.toggle("practice-match-active", visible.match);
  if (import.meta.env?.DEV) console.debug(`[Bishoply Practice] view -> ${practiceView}`, {
    "selector.hidden": Boolean(practiceLanding?.hidden),
    "loading.hidden": Boolean(practiceLoading?.hidden),
    "match.hidden": Boolean(practiceSession?.hidden),
  });
  const page = practicePage;
  const onPracticePage = Boolean(page && document.querySelector("#page-practice.active"));
  if (sidebarProfile) sidebarProfile.hidden = onPracticePage && practiceView !== "select";
  if (onPracticePage && previousView !== practiceView) {
    resetPageScroll(page);
  }
}
try {
  practiceEvalVisible = localStorage.getItem("bishoply.practice.evalbar") !== "off";
} catch {}
const gameReview = new GameReview($("#game-review"), apiFetch, position => {
  reviewPosition = position;
  selectedSquare = null;
  $("#match-mode-label").textContent = position ? "Post-game analysis · Replay" : "Current match";
  if (currentGame) renderBoard();
}, () => { reviewFlipped = !reviewFlipped; renderBoard(); }, () => gameResult.open());
const practiceReview = new GameReview($("#practice-review"), apiFetch, position => {
  practiceReviewPosition = position;
  practiceSelectedSquare = null;
  if (practiceGame) renderPracticeBoard();
}, () => {
  practiceReviewFlipped = !practiceReviewFlipped;
  renderPracticeBoard();
}, () => gameResult.open(), {
  rootSelector: "#page-practice",
  title: "Practice Review",
  baseTitle: "Practice Game",
  requestPath: (game) => `/api/practice/games/${encodeURIComponent(game.game_id)}/review`,
  requestHeaders: () => practiceAccessKey ? { "X-Practice-Key": practiceAccessKey } : {},
  staged: true,
});
const gameResult = new GameResult($("#game-result-dialog"), () => gameReview.open());

let appReady = false;

let legalMoves = [];
let canMove = false;
let playerColor = null;
let selectedSquare = null;
let boardPieces = {};

let syncTimer = null;
let syncBusy = false;

let annotationArrows = [];
let annotationCircles = [];

let annotationStartSquare = null;
let annotationDragging = false;
let annotationStartPoint = null;

let resignConfirmationActive = false;
let resignConfirmationTimer = null;

const handledFinishedGames = new Set();


const isMobileOrIOS =
  /iPhone|iPad|iPod/i.test(navigator.userAgent) ||
  window.matchMedia("(pointer: coarse)").matches;


const pieceMap = {
  p: "♟",
  r: "♜",
  n: "♞",
  b: "♝",
  q: "♛",
  k: "♚",

  P: "♟",
  R: "♜",
  N: "♞",
  B: "♝",
  Q: "♛",
  K: "♚",
};


function publicInt(value) {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return 0;
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return 0;
  }

  return Math.round(number);
}


function formatNumber(value) {
  return publicInt(value).toLocaleString();
}


function signedNumber(value) {
  const number = publicInt(value);

  if (number > 0) {
    return `+${number}`;
  }

  return String(number);
}


function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function setStatus(message) {
  if (statusElement) {
    statusElement.textContent = message;
  }
}

function practiceDebug(event, details = {}) {
  if (import.meta.env?.DEV) {
    console.debug(`[Bishoply Practice] ${event}`, details);
  }
}


function setConnectionLabel(message) {
  if (connectionLabel) {
    connectionLabel.textContent = message;
  }
}


function setCheck(element, message) {
  if (element) {
    element.textContent = message;
  }
}


function formatIntegrityReason(reason) {
  const labels = {
    integrity_checks_passed: "Integrity checks passed",
    early_resignation: "Early resignation",
    rapid_resignation: "Game ended too quickly",
    pair_daily_rating_limit: "Daily opponent rating limit reached",
    game_marked_unrated: "Game marked unrated",
    unrated_mode: "Unrated game mode",
    self_play: "Self-play is not rateable",
    missing_player: "Missing player",
    game_not_completed: "Game was not completed",
  };

  if (labels[reason]) {
    return labels[reason];
  }

  return String(reason || "Unrated")
    .replaceAll("_", " ");
}


function setControlsEnabled(enabled) {
  [
    createGameButton,
    joinGameButton,
    moveButton,
    refreshHistoryButton,
    practiceHintButton,
    practiceBestButton,
    practiceWhyButton,
    practiceThreatButton,
    practiceSpeakButton,
    practiceResignButton,
    practiceUndoButton,
    practiceRestartButton,
    practiceNewOpponentButton,
    practiceEvalToggle,
  ].forEach((button) => {
    if (button) {
      button.disabled = !enabled;
    }
  });

  if (joinGameInput) {
    joinGameInput.disabled = !enabled;
  }

  if (moveInput) {
    moveInput.disabled = !enabled;
  }

  if (practiceSoundButton) {
    practiceSoundButton.disabled = !enabled;
  }
}


async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const normalizedPath = typeof path === "string" && path.startsWith("/") ? path : "";
  const publicPath = normalizedPath === "/health" || normalizedPath === "/api/health" || normalizedPath === "/api/auth/discord" || normalizedPath === "/api/auth/session" || normalizedPath === "/api/practice/bots" || /^\/api\/auth\/(google|apple|discord)\/start$/.test(normalizedPath);
  // FastAPI protects these routes with a required Authorization header. Do
  // not send a guaranteed-422 request while Discord authentication is still
  // completing; surface the normal safe auth state instead.
  if (normalizedPath.startsWith("/api/") && !publicPath && !discordAccessToken && !webSessionAuthenticated) {
    throw new ApiError("Discord authentication is still loading. Please try again shortly.", "unauthorized", 401);
  }
  if (discordAccessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${discordAccessToken}`);
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs || 12000);
  let response;
  try {
    const target = backendRequestUrl(path);
    response = await fetch(target, { ...options, credentials: options.credentials || apiTransport.credentials(), headers: apiTransport.headers(headers), signal: options.signal || controller.signal });
  } catch (error) {
    if (error?.name === "AbortError") throw new ApiError("Request timed out. Please try again.", "timeout", 0);
    throw new ApiError("Connection lost. Check your connection and try again.", "network_error", 0);
  } finally {
    window.clearTimeout(timeout);
  }

  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const kind = response.status === 401 ? "unauthorized" : response.status === 403 ? "forbidden" : response.status === 404 ? "not_found" : response.status === 409 ? "conflict" : response.status === 422 ? "validation_error" : response.status === 429 ? "rate_limited" : response.status >= 500 ? "server_error" : "request_error";
    const retryHint = response.headers.get("Retry-After");
    const message = kind === "unauthorized" ? "Your Discord session expired. Reopen the Activity to reconnect." : kind === "forbidden" ? "You do not have access to this resource." : kind === "not_found" ? "That Bishoply resource is no longer available." : kind === "rate_limited" ? `You're doing that too quickly. Try again in a moment.${retryHint ? ` Retry in ${retryHint}s.` : ""}` : kind === "server_error" ? "Bishoply is having trouble right now. Please try again." : formatApiError(data, response.status);
    throw new ApiError(message, kind, response.status, response.headers.get("Retry-After"));
  }

  return data;
}

class ApiError extends Error {
  constructor(message, kind = "request_error", status = 0, retryAfter = null) {
    super(message); this.name = "ApiError"; this.kind = kind; this.status = status; this.retryAfter = retryAfter;
  }
}

function formatApiError(data, status = 0) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (typeof data?.message === "string" && data.message.trim()) return data.message;
  if (typeof data?.error === "string" && data.error.trim()) return data.error;
  if (Array.isArray(detail)) {
    const messages = detail.map(item => typeof item === "string" ? item : item?.msg || item?.message).filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.error === "string") return detail.error;
    try {
      const nested = Object.values(detail).flatMap(value => Array.isArray(value) ? value : [value]).filter(value => typeof value === "string");
      if (nested.length) return nested.join("; ");
    } catch {}
  }
  return status ? `Request failed (${status}).` : "Request failed.";
}


function installStyles() {
  if ($("#bishoply-v2-styles")) {
    return;
  }

  const style = document.createElement("style");

  style.id = "bishoply-v2-styles";

  style.textContent = `
    .developer-move-panel {
      display: none !important;
    }

    .bishoply-board {
      position: relative;
    }

    .bishoply-board .square {
      cursor: default;
    }

    .bishoply-board .square.own-piece {
      cursor: pointer;
    }

    .bishoply-board .square.selected-square {
      z-index: 8;

      box-shadow:
        inset 0 0 0 4px rgba(243, 228, 186, 0.95),
        inset 0 0 34px rgba(220, 196, 139, 0.42),
        0 0 18px rgba(220, 196, 139, 0.25);
    }

    .bishoply-board .square.legal-target {
      cursor: pointer;
    }

    .bishoply-board .square.legal-target::after {
      content: "";

      position: absolute;
      z-index: 7;

      width: 22%;
      aspect-ratio: 1 / 1;

      border-radius: 999px;

      background: rgba(23, 30, 18, 0.42);

      pointer-events: none;
    }

    .bishoply-board .square.dark.legal-target::after {
      background: rgba(245, 235, 211, 0.46);
    }

    .bishoply-board .square.legal-capture::after {
      content: "";

      position: absolute;
      inset: 8%;

      z-index: 7;

      border:
        clamp(3px, 0.35vw, 5px)
        solid
        rgba(220, 196, 139, 0.72);

      border-radius: 999px;

      background: transparent;

      pointer-events: none;
    }

    .bishoply-board .square.last-move:not(.selected-square) {
      box-shadow:
        inset 0 0 0 3px rgba(208, 173, 86, 0.48),
        inset 0 0 30px rgba(208, 173, 86, 0.18);
    }

    .bishoply-board .piece,
    .bishoply-board .coord-file,
    .bishoply-board .coord-rank {
      pointer-events: none;
    }

    .board-thinking {
      pointer-events: none;
      opacity: 0.78;
    }

    .finished-board .square {
      cursor: default !important;
    }


    .annotation-layer {
      position: absolute;

      inset: 12px;

      z-index: 20;

      pointer-events: none;
    }

    .annotation-layer svg {
      width: 100%;
      height: 100%;

      display: block;
      overflow: visible;
    }

    .annotation-arrow {
      stroke: rgba(220, 196, 139, 0.82);
      stroke-width: 2.25;
      stroke-linecap: round;
      fill: none;
    }

    .annotation-arrow-head {
      fill: rgba(220, 196, 139, 0.88);
    }

    .annotation-circle {
      fill: none;

      stroke: rgba(220, 196, 139, 0.88);
      stroke-width: 2.15;
    }

    .annotation-help {
      margin-top: 10px;

      display: flex;
      justify-content: space-between;
      align-items: center;

      gap: 10px;

      color: rgba(247, 242, 232, 0.48);

      font-size: 11px;
    }

    .annotation-clear {
      min-height: 30px !important;

      padding: 0 10px !important;

      border-radius: 10px !important;

      color: rgba(247, 242, 232, 0.72) !important;

      background: rgba(255, 255, 255, 0.055) !important;

      border:
        1px solid
        rgba(255, 255, 255, 0.08) !important;

      box-shadow: none !important;

      font-size: 11px !important;
    }


    .bishoply-v2-badge {
      display: inline-flex;
      align-items: center;

      min-height: 28px;

      padding: 0 10px;

      border-radius: 999px;

      font-size: 10px;
      font-weight: 800;

      letter-spacing: 0.08em;
      text-transform: uppercase;

      border:
        1px solid
        rgba(220, 196, 139, 0.22);

      color: #ead9a7;

      background:
        rgba(220, 196, 139, 0.08);
    }

    .bishoply-v2-badge.unrated {
      color: rgba(247, 242, 232, 0.66);

      border-color:
        rgba(255, 255, 255, 0.10);

      background:
        rgba(255, 255, 255, 0.04);
    }

    .bishoply-v2-badge.provisional {
      color: #d8bd77;

      border-color:
        rgba(216, 189, 119, 0.28);

      background:
        rgba(216, 189, 119, 0.09);
    }


    .profile-rating-hero {
      margin-top: 18px;

      display: grid;

      grid-template-columns:
        repeat(2, minmax(0, 1fr));

      gap: 12px;
    }

    .profile-rating-primary {
      padding: 18px;

      border-radius: 17px;

      border:
        1px solid
        rgba(220, 196, 139, 0.18);

      background:
        linear-gradient(
          145deg,
          rgba(220, 196, 139, 0.09),
          rgba(255, 255, 255, 0.025)
        );
    }

    .profile-rating-primary span {
      display: block;

      margin-bottom: 7px;

      color: rgba(247, 242, 232, 0.52);

      font-size: 10px;
      font-weight: 700;

      letter-spacing: 0.10em;
      text-transform: uppercase;
    }

    .profile-rating-primary strong {
      display: block;

      color: #f5e9c8;

      font-size: clamp(27px, 4vw, 38px);
      line-height: 1;
    }

    .profile-rating-primary small {
      display: block;

      margin-top: 8px;

      color: rgba(247, 242, 232, 0.48);

      font-size: 11px;
    }


    .game-result-card {
      margin-top: 14px;

      padding: 16px;

      border-radius: 16px;

      border:
        1px solid
        rgba(220, 196, 139, 0.24);

      background:
        linear-gradient(
          145deg,
          rgba(220, 196, 139, 0.09),
          rgba(255, 255, 255, 0.035)
        );
    }

    .game-result-card .result-label {
      display: block;

      margin-bottom: 5px;

      color: rgba(247, 242, 232, 0.52);

      font-size: 10px;
      font-weight: 800;

      letter-spacing: 0.10em;
      text-transform: uppercase;
    }

    .game-result-card .result-title {
      margin: 0;

      color: #f5e9c8;

      font-size: 23px;
      font-weight: 800;
    }

    .result-meta {
      margin-top: 6px;

      color: rgba(247, 242, 232, 0.55);

      font-size: 12px;
    }

    .result-competition-grid {
      margin-top: 15px;

      display: grid;

      grid-template-columns:
        repeat(2, minmax(0, 1fr));

      gap: 10px;
    }

    .result-stat {
      padding: 12px;

      border-radius: 13px;

      background:
        rgba(255, 255, 255, 0.035);

      border:
        1px solid
        rgba(255, 255, 255, 0.065);
    }

    .result-stat span {
      display: block;

      color: rgba(247, 242, 232, 0.48);

      font-size: 9px;
      font-weight: 700;

      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .result-stat strong {
      display: block;

      margin-top: 5px;

      color: #f5e9c8;

      font-size: 17px;
    }

    .result-stat em {
      display: block;

      margin-top: 3px;

      font-style: normal;

      font-size: 12px;
      font-weight: 800;
    }

    .rating-positive {
      color: #9bd39b;
    }

    .rating-negative {
      color: #e49a9a;
    }

    .rating-neutral {
      color: rgba(247, 242, 232, 0.68);
    }

    .integrity-message {
      margin-top: 12px;

      padding-top: 12px;

      border-top:
        1px solid
        rgba(255, 255, 255, 0.07);

      color: rgba(247, 242, 232, 0.54);

      font-size: 11px;
      line-height: 1.5;
    }


    .game-action-row {
      margin-top: 14px;

      display: flex;
      gap: 10px;

      flex-wrap: wrap;
    }

    .resign-button {
      min-height: 40px;

      padding: 0 16px;

      border-radius: 12px;

      border:
        1px solid
        rgba(225, 110, 110, 0.24);

      background:
        rgba(150, 55, 55, 0.12);

      color: #eeb3b3;

      cursor: pointer;

      font: inherit;
      font-size: 12px;
      font-weight: 700;
    }

    .resign-button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }


    @media (max-width: 680px) {
      .profile-rating-hero,
      .result-competition-grid {
        grid-template-columns: 1fr;
      }
    }
  `;

  document.head.appendChild(style);

  if (moveInput) {
    const panel =
      moveInput.closest(".glass-panel");

    if (panel) {
      panel.classList.add(
        "developer-move-panel"
      );
    }
  }
}


function showPage(pageName) {
  $$(".page").forEach((page) => {
    page.classList.remove("active");
  });

  $$(".nav-item").forEach((item) => {
    item.classList.remove("active");
  });

  const selectedPage =
    $(`#page-${pageName}`);

  const selectedNav =
    $(`.nav-item[data-page="${pageName}"]`);

  if (selectedPage) {
    selectedPage.classList.add("active");
  }

  if (selectedNav) {
    selectedNav.classList.add("active");
  }

  if (sidebarProfile && pageName !== "practice") sidebarProfile.hidden = false;

  if (pageName !== "practice") resetPageScroll(selectedPage);

  if (
    pageName === "game" &&
    !currentGame
  ) {
    renderEmptyGame();
  }

  if (pageName === "practice") {
    renderPracticeShell();
  } else if (practiceReview.active) {
    practiceReview.close();
  }
}

function resetPageScroll(page) {
  if (!page) return;
  window.scrollTo(0, 0);
  page.scrollTo(0, 0);
  document.activeElement?.blur?.();
}


function getMyColor(game) {
  if (
    !currentProfile ||
    !game
  ) {
    return null;
  }

  const myId =
    String(
      currentProfile.discord_id
    );

  const whiteId =
    game.white
      ? String(
          game.white.discord_id
        )
      : null;

  const blackId =
    game.black
      ? String(
          game.black.discord_id
        )
      : null;

  if (myId === whiteId) {
    return "white";
  }

  if (myId === blackId) {
    return "black";
  }

  return null;
}


function getMyResult(game) {
  const color =
    getMyColor(game);

  if (!color) {
    return "spectator";
  }

  if (game.status === "draw") {
    return "draw";
  }

  if (game.status === "white_win") {
    return (
      color === "white"
        ? "win"
        : "loss"
    );
  }

  if (game.status === "black_win") {
    return (
      color === "black"
        ? "win"
        : "loss"
    );
  }

  return "in_progress";
}


function getResultTitle(game) {
  const result =
    getMyResult(game);

  if (result === "win") {
    return "Victory";
  }

  if (result === "loss") {
    return "Defeat";
  }

  if (result === "draw") {
    return "Draw";
  }

  if (game.status === "white_win") {
    return "White wins";
  }

  if (game.status === "black_win") {
    return "Black wins";
  }

  return "Game complete";
}


function getMyCompetitiveData(game) {
  const color =
    getMyColor(game);

  if (
    !color ||
    !game?.competitive
  ) {
    return null;
  }

  return (
    color === "white"
      ? game.competitive.white
      : game.competitive.black
  );
}


async function checkBackend() {
  const data =
    await apiFetch("/health");

  if (!(data?.status === "ok" || data?.ok === true)) {
    throw new Error(
      "Backend unhealthy."
    );
  }

  setCheck(
    apiCheck,
    "API connected"
  );
}


function renderProfile(profile) {
  const displayName =
    profile.display_name ||
    profile.username ||
    "Bishoply Player";

  const avatar =
    profile.avatar_url
      ? `
        <img
          src="${escapeHtml(profile.avatar_url)}"
          alt="Discord avatar"
        >
      `
      : escapeHtml(
          displayName
            .charAt(0)
            .toUpperCase()
        );

  const provisionalBadge =
    profile.provisional
      ? `
        <span class="bishoply-v2-badge provisional">
          Provisional
        </span>
      `
      : `
        <span class="bishoply-v2-badge">
          Established
        </span>
      `;

  if (sidebarProfile) {
    sidebarProfile.innerHTML = `
      <div class="avatar">
        ${avatar}
      </div>

      <div>
        <strong>
          ${escapeHtml(displayName)}
        </strong>

        <span>
          ${formatNumber(profile.sr)} SR
          ·
          ${formatNumber(profile.rating)}
        </span>
      </div>

      <section class="profile-customization" aria-label="Customization">
        <div class="eyebrow gold">Customization</div>
        <div id="profile-cosmetics-grid" class="profile-cosmetics-grid"><span>Loading customization…</span></div>
      </section>
    `;
    renderCosmetics();
  }

  if (profilePageCard) {
    profilePageCard.innerHTML = `
      <div class="profile-hero-row">
        <div class="big-avatar">
          ${avatar}
        </div>

        <div>
          <div class="eyebrow gold">
            ${escapeHtml(profile.title || "Bishoply Player")}
          </div>

          <h2>
            ${escapeHtml(displayName)}
          </h2>

          <p>
            @${escapeHtml(profile.username)}
          </p>

          ${provisionalBadge}
        </div>
      </div>

      <div class="profile-rating-hero">
        <div class="profile-rating-primary">
          <span>
            Bishoply SR
          </span>

          <strong>
            ${formatNumber(profile.sr)}
          </strong>

          <small>
            Peak ${formatNumber(profile.peak_sr)}
          </small>
        </div>

        <div class="profile-rating-primary">
          <span>
            Bishoply Chess Rating
          </span>

          <strong>
            ${formatNumber(profile.rating)}
          </strong>

          <small>
            Peak ${formatNumber(profile.peak_rating)}
            ·
            ${escapeHtml(profile.rating_confidence)} confidence
          </small>
        </div>
      </div>

      <div class="profile-stat-grid">
        <div>
          <span>Rated Games</span>
          <strong>
            ${formatNumber(profile.rated_games)}
          </strong>
        </div>

        <div>
          <span>Rating RD</span>
          <strong>
            ${formatNumber(profile.rating_deviation)}
          </strong>
        </div>

        <div>
          <span>Wins</span>
          <strong>
            ${formatNumber(profile.wins)}
          </strong>
        </div>

        <div>
          <span>Losses</span>
          <strong>
            ${formatNumber(profile.losses)}
          </strong>
        </div>

        <div>
          <span>Draws</span>
          <strong>
            ${formatNumber(profile.draws)}
          </strong>
        </div>

        <div>
          <span>Win Rate</span>
          <strong>
            ${escapeHtml(profile.win_rate)}%
          </strong>
        </div>

        <div>
          <span>Current Streak</span>
          <strong>
            ${formatNumber(profile.current_win_streak)}
          </strong>
        </div>

        <div>
          <span>Best Streak</span>
          <strong>
            ${formatNumber(profile.best_win_streak)}
          </strong>
        </div>

        <div>
          <span>Placement Remaining</span>
          <strong>
            ${formatNumber(profile.placement_games_remaining)}
          </strong>
        </div>

        <div>
          <span>Games Rewarded</span>
          <strong>
            ${formatNumber(profile.games_rewarded)}
          </strong>
        </div>
      </div>
    `;
  }

  if (homeRating) {
    homeRating.textContent =
      formatNumber(
        profile.rating
      );
  }

  if (homeRank) {
    homeRank.textContent =
      `${formatNumber(profile.sr)} SR`;
  }

  if (homeGames) {
    homeGames.textContent =
      formatNumber(
        profile.rated_games
      );
  }

  if (homeWinRate) {
    homeWinRate.textContent =
      `${profile.win_rate}%`;
  }
}

async function loadProfileCosmetics() {
  if (!currentProfile) return;
  try {
    profileCosmetics = await apiFetch('/api/profile/cosmetics');
  } catch { profileCosmetics = { owned: [], loadout: {} }; }
  renderCosmetics();
}

function renderCosmetics() {
  const target = document.querySelector('#profile-cosmetics-grid');
  if (!target) return;
  const categories = { board_skin: 'Board', piece_set: 'Pieces', board_border: 'Border', profile_frame: 'Profile Frame', background_effect: 'Background Effect', sound_pack: 'Sound Pack' };
  const owned = profileCosmetics.owned || [];
  target.innerHTML = Object.entries(categories).map(([category, label]) => {
    const items = owned.filter(item => item.category === category);
    return `<div class="cosmetic-slot"><strong>${label}</strong><span>${items.length ? items.map(item => escapeHtml(item.name)).join(', ') : 'Locked'}</span></div>`;
  }).join('');
}

function showUsernameOnboarding() {
  if (!webAuthScreen) return;
  webAuthScreen.hidden = false;
  const card = webAuthScreen.querySelector('.web-auth-card');
  if (!card) return;
  card.innerHTML = `<div class="brand-mark">♝</div><h2>Choose your Bishoply username</h2><p>This name identifies you across Bishoply.</p><form id="username-onboarding-form"><input name="username" minlength="3" maxlength="20" pattern="[A-Za-z0-9_]{3,20}" required placeholder="Your username" autocomplete="off"><button class="gold-button full" type="submit">Continue</button></form><button class="dark-button full" id="username-signout" type="button">Sign out</button><small id="username-onboarding-status"></small>`;
  card.querySelector('form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = card.querySelector('#username-onboarding-status');
    try {
      const value = new FormData(event.currentTarget).get('username');
      currentProfile = await apiFetch('/api/profile/username', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: value }) });
      webAuthScreen.hidden = true; renderProfile(currentProfile); setStatus('Bishoply is ready.');
    } catch (error) { status.textContent = error?.message || 'Username is unavailable.'; }
  });
  card.querySelector('#username-signout').addEventListener('click', () => accountLogoutButton?.click());
}


function renderEmptyGame() {
  selectedSquare = null;

  legalMoves = [];
  boardPieces = {};

  canMove = false;
  playerColor = null;

  annotationArrows = [];
  annotationCircles = [];

  if (gameInfo) {
    gameInfo.innerHTML = `
      <div class="empty-mini">
        <strong>
          No duel loaded.
        </strong>

        <span>
          Create or join a game from Play.
        </span>
      </div>
    `;
  }

  if (boardElement) {
    boardElement.className =
      "board-empty";

    boardElement.innerHTML = `
      <div class="empty-board-card">
        <div class="empty-board-icon">
          ♝
        </div>

        <h3>
          Bishoply Board
        </h3>

        <p>
          Create or join a duel and your
          live board will appear here.
        </p>

        <button
          class="gold-button"
          data-empty-play-button
          type="button"
        >
          Start Duel
        </button>
      </div>
    `;
  }

  if (movesList) {
    movesList.innerHTML = `
      <div class="empty-mini">
        <strong>
          No moves yet.
        </strong>

        <span>
          Your move history will appear here.
        </span>
      </div>
    `;
  }

  const button =
    $("[data-empty-play-button]");

  if (button) {
    button.addEventListener(
      "click",
      () => {
        showPage("play");
      }
    );
  }
}


function parseFenPieces(fen) {
  const result = {};

  if (!fen) {
    return result;
  }

  const ranks =
    fen
      .split(" ")[0]
      .split("/");

  for (
    let rankIndex = 0;
    rankIndex < 8;
    rankIndex += 1
  ) {
    let fileIndex = 0;

    for (
      const char
      of ranks[rankIndex]
    ) {
      const empty =
        Number(char);

      if (
        Number.isInteger(empty)
      ) {
        fileIndex += empty;

        continue;
      }

      const file =
        String.fromCharCode(
          97 + fileIndex
        );

      const rank =
        8 - rankIndex;

      result[
        `${file}${rank}`
      ] = {
        symbol: char,

        color:
          char ===
          char.toUpperCase()
            ? "white"
            : "black",
      };

      fileIndex += 1;
    }
  }

  return result;
}


function getLastMoveSquares(moves) {
  if (!moves?.length) {
    return [];
  }

  const uci =
    moves[
      moves.length - 1
    ]?.uci;

  if (
    !uci ||
    uci.length < 4
  ) {
    return [];
  }

  return [
    uci.slice(0, 2),
    uci.slice(2, 4),
  ];
}


function getDisplaySquares(game, color = null, reviewActive = false, flipped = false) {
  const normal = color || getMyColor(game) || "white";
  const orientation = reviewActive && flipped ? (normal === "white" ? "black" : "white") : normal;

  const filesNormal = [
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
  ];

  const ranksNormal = [
    8,
    7,
    6,
    5,
    4,
    3,
    2,
    1,
  ];

  const files =
    orientation === "black"
      ? [...filesNormal].reverse()
      : filesNormal;

  const ranks =
    orientation === "black"
      ? [...ranksNormal].reverse()
      : ranksNormal;

  const squares = [];

  for (const rank of ranks) {
    for (const file of files) {
      squares.push(
        `${file}${rank}`
      );
    }
  }

  return {
    squares,
    orientation,
  };
}

function renderBoardSurface(targetBoard, game, {
  selectedSquare = null,
  legalMoves = [],
  canMove = false,
  playerColor = null,
  reviewPosition = null,
  reviewFlipped = false,
  extraClass = "",
} = {}) {
  if (!targetBoard) {
    return { orientation: "white", boardPieces: {} };
  }

  const displayGame = reviewPosition ? { ...game, ...reviewPosition } : game;

  if (!displayGame?.fen) {
    targetBoard.className = "board-empty";
    targetBoard.innerHTML = "";
    return { orientation: "white", boardPieces: {} };
  }

  const { squares, orientation } = getDisplaySquares(
    displayGame,
    playerColor,
    Boolean(reviewPosition),
    reviewFlipped
  );

  const boardPieces = parseFenPieces(displayGame.fen);
  const lastMoveSquares = getLastMoveSquares(displayGame.moves || []);
  const legalDestinations = !reviewPosition && selectedSquare
    ? legalMoves.filter((move) => move.from === selectedSquare)
    : [];

  let html = "";

  for (let index = 0; index < squares.length; index += 1) {
    const square = squares[index];
    const file = square[0];
    const rank = Number(square[1]);
    const fileIndex = file.charCodeAt(0) - 97;
    const rankIndex = 8 - rank;
    const isLight = (fileIndex + rankIndex) % 2 === 0;
    const piece = boardPieces[square];
    const isOwnPiece = Boolean(piece && playerColor && piece.color === playerColor);
    const destinationMove = legalDestinations.find((move) => move.to === square);
    const isLegalTarget = Boolean(destinationMove);
    const isCapture = Boolean(
      destinationMove &&
      (boardPieces[square] ||
        (boardPieces[destinationMove.from]?.symbol.toLowerCase() === "p" && destinationMove.from[0] !== square[0]))
    );
    const displayRow = Math.floor(index / 8);
    const displayColumn = index % 8;
    const rankLabel = displayColumn === 0 ? `<span class="coord-rank">${rank}</span>` : "";
    const fileLabel = displayRow === 7 ? `<span class="coord-file">${file}</span>` : "";

    let pieceHtml = "";
    if (piece) {
      const pieceClass = piece.color === "white" ? "piece-white" : "piece-black";
      pieceHtml = `<span class="piece ${pieceClass}">${pieceMap[piece.symbol]}</span>`;
    }

    const classes = [
      "square",
      isLight ? "light" : "dark",
      lastMoveSquares.includes(square) ? "last-move" : "",
      isOwnPiece && canMove ? "own-piece" : "",
      !reviewPosition && square === selectedSquare ? "selected-square" : "",
      isLegalTarget ? "legal-target" : "",
      isCapture ? "legal-capture" : "",
    ].filter(Boolean).join(" ");

    html += `
      <button
        class="${classes}"
        data-square="${square}"
        aria-label="${square}"
        type="button"
      >
        ${rankLabel}
        ${fileLabel}
        ${pieceHtml}
      </button>
    `;
  }

  const finishClass = displayGame.status === "active" ? "" : " finished-board";
  targetBoard.className = `board bishoply-board orientation-${orientation}${finishClass}${extraClass ? ` ${extraClass}` : ""}`;
  targetBoard.innerHTML = html;

  return { orientation, boardPieces, squares, displayGame };
}


function renderBoard() {
  const displayGame = reviewPosition ? { ...currentGame, ...reviewPosition } : currentGame;
  if (!displayGame?.fen) {
    renderEmptyGame();

    return;
  }

  const view = renderBoardSurface(boardElement, currentGame, {
    selectedSquare,
    legalMoves,
    canMove,
    playerColor,
    reviewPosition,
    reviewFlipped,
  });
  boardPieces = view.boardPieces || {};
  bindBoardSquares(boardElement, handleSquareClick);

  if (!isMobileOrIOS && !reviewPosition) {
    bindAnnotationEvents();

    renderAnnotations();

    renderAnnotationControls();
  } else {
    removeAnnotationControls();
  }
}


function bindBoardSquares(target = boardElement, handler = handleSquareClick) {
  if (!target || !handler) {
    return;
  }

  target.querySelectorAll(".square")
    .forEach(
      (button) => {
        button.addEventListener(
          "click",
          async () => {
            try {
              await handler(button.dataset.square);
            } catch (error) {
              setStatus(
                `Bishoply error: ${error.message}`
              );
            }
          }
        );
      }
    );
}


function selectSquare(square) {
  const available =
    legalMoves.filter(
      (move) =>
        move.from === square
    );

  if (!available.length) {
    selectedSquare = null;

    renderBoard();

    return;
  }

  selectedSquare =
    square;

  renderBoard();

  setStatus(
    `Selected ${square}. Choose a destination.`
  );
}


async function handleSquareClick(square) {
  if (reviewPosition) return;
  if (!currentGame) {
    return;
  }

  if (
    currentGame.status ===
    "waiting"
  ) {
    setStatus(
      "Waiting for your opponent to join."
    );

    return;
  }

  if (
    currentGame.status !==
    "active"
  ) {
    setStatus(
      "This game is finished."
    );

    return;
  }

  if (!canMove) {
    setStatus(
      "Waiting for your opponent."
    );

    return;
  }

  const piece =
    boardPieces[square];

  if (selectedSquare) {
    const destinationMoves =
      legalMoves.filter(
        (move) =>
          move.from ===
            selectedSquare &&
          move.to ===
            square
      );

    if (
      destinationMoves.length
    ) {
      let chosenMove =
        destinationMoves[0];

      const queen =
        destinationMoves.find(
          (move) =>
            move.promotion ===
            "queen"
        );

      if (queen) {
        chosenMove = queen;
      }

      await submitBoardMove(
        chosenMove.uci
      );

      return;
    }

    if (
      piece &&
      piece.color ===
        playerColor
    ) {
      selectSquare(square);

      return;
    }

    selectedSquare = null;

    renderBoard();

    return;
  }

  if (
    piece &&
    piece.color ===
      playerColor
  ) {
    selectSquare(square);
  }
}


async function loadLegalMoves() {
  legalMoves = [];
  canMove = false;

  if (
    !currentGame?.game_id ||
    !currentProfile?.discord_id
  ) {
    return;
  }

  if (
    currentGame.status !==
    "active"
  ) {
    selectedSquare = null;

    renderBoard();

    return;
  }

  try {
    const data =
      await apiFetch(
        `/api/games/${currentGame.game_id}/legal-moves?discord_id=${encodeURIComponent(currentProfile.discord_id)}`
      );

    legalMoves =
      data.moves || [];

    canMove =
      Boolean(
        data.can_move
      );

    playerColor =
      data.your_color;

    renderBoard();

    setStatus(
      canMove
        ? `Your turn · ${playerColor}`
        : `Waiting for ${currentGame.turn}.`
    );
  } catch (error) {
    legalMoves = [];
    canMove = false;

    renderBoard();

    if (
      error.message ===
      "You are not a player in this game"
    ) {
      setStatus(
        "Viewing game as spectator."
      );

      return;
    }

    throw error;
  }
}


async function submitBoardMove(uci) {
  if (
    !currentGame?.game_id ||
    !currentProfile?.discord_id
  ) {
    return;
  }

  selectedSquare = null;

  boardElement.classList.add(
    "board-thinking"
  );

  try {
    const data =
      await apiFetch(
        `/api/games/${currentGame.game_id}/move`,
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body:
            JSON.stringify({
              discord_id:
                currentProfile.discord_id,

              move:
                uci,
            }),
        }
      );

    await renderGame(
      data.game
    );

    await loadHistory();

    if (
      data.game.status ===
      "active"
    ) {
      setStatus(
        `Move played: ${data.move.san}`
      );
    }
  } finally {
    boardElement.classList.remove(
      "board-thinking"
    );
  }
}


function getSquareElement(square) {
  return boardElement.querySelector(
    `.square[data-square="${square}"]`
  );
}


function getSquareCenterPercent(square) {
  const element =
    getSquareElement(square);

  if (!element) {
    return null;
  }

  const boardRect =
    boardElement.getBoundingClientRect();

  const squareRect =
    element.getBoundingClientRect();

  return {
    x:
      (
        squareRect.left -
        boardRect.left +
        squareRect.width / 2
      )
      /
      boardRect.width
      *
      100,

    y:
      (
        squareRect.top -
        boardRect.top +
        squareRect.height / 2
      )
      /
      boardRect.height
      *
      100,
  };
}


function toggleCircle(square) {
  const index =
    annotationCircles.indexOf(
      square
    );

  if (index >= 0) {
    annotationCircles.splice(
      index,
      1
    );
  } else {
    annotationCircles.push(
      square
    );
  }

  renderAnnotations();
}


function toggleArrow(from, to) {
  const index =
    annotationArrows.findIndex(
      (arrow) =>
        arrow.from === from &&
        arrow.to === to
    );

  if (index >= 0) {
    annotationArrows.splice(
      index,
      1
    );
  } else {
    annotationArrows.push({
      from,
      to,
    });
  }

  renderAnnotations();
}


function clearAnnotations() {
  annotationArrows = [];
  annotationCircles = [];

  renderAnnotations();

  setStatus(
    "Board annotations cleared."
  );
}


function bindAnnotationEvents() {
  if (isMobileOrIOS) {
    return;
  }

  $$(".bishoply-board .square")
    .forEach(
      (element) => {
        element.addEventListener(
          "contextmenu",
          (event) => {
            event.preventDefault();
          }
        );

        element.addEventListener(
          "pointerdown",
          (event) => {
            if (
              event.button !== 2
            ) {
              return;
            }

            event.preventDefault();

            annotationStartSquare =
              element.dataset.square;

            annotationDragging =
              false;

            annotationStartPoint = {
              x: event.clientX,
              y: event.clientY,
            };
          }
        );

        element.addEventListener(
          "pointermove",
          (event) => {
            if (
              event.buttons !== 2 ||
              !annotationStartPoint
            ) {
              return;
            }

            const dx =
              event.clientX -
              annotationStartPoint.x;

            const dy =
              event.clientY -
              annotationStartPoint.y;

            if (
              Math.sqrt(
                dx * dx +
                dy * dy
              ) > 8
            ) {
              annotationDragging =
                true;
            }
          }
        );

        element.addEventListener(
          "pointerup",
          (event) => {
            if (
              event.button !== 2 ||
              !annotationStartSquare
            ) {
              return;
            }

            event.preventDefault();

            const endSquare =
              element.dataset.square;

            if (
              annotationDragging &&
              endSquare !==
                annotationStartSquare
            ) {
              toggleArrow(
                annotationStartSquare,
                endSquare
              );
            } else {
              toggleCircle(
                annotationStartSquare
              );
            }

            annotationStartSquare =
              null;

            annotationDragging =
              false;

            annotationStartPoint =
              null;
          }
        );
      }
    );
}


function renderAnnotations() {
  if (
    isMobileOrIOS ||
    !currentGame ||
    !boardElement.classList.contains(
      "bishoply-board"
    )
  ) {
    return;
  }

  let layer =
    boardElement.querySelector(
      ".annotation-layer"
    );

  if (!layer) {
    layer =
      document.createElement(
        "div"
      );

    layer.className =
      "annotation-layer";

    boardElement.appendChild(
      layer
    );
  }

  const arrows =
    annotationArrows
      .map((arrow) => {
        const from =
          getSquareCenterPercent(
            arrow.from
          );

        const to =
          getSquareCenterPercent(
            arrow.to
          );

        if (!from || !to) {
          return "";
        }

        const dx =
          to.x - from.x;

        const dy =
          to.y - from.y;

        const length =
          Math.sqrt(
            dx * dx +
            dy * dy
          );

        if (!length) {
          return "";
        }

        const trim =
          4.3;

        const ux =
          dx / length;

        const uy =
          dy / length;

        return `
          <line
            class="annotation-arrow"
            x1="${from.x}"
            y1="${from.y}"
            x2="${to.x - ux * trim}"
            y2="${to.y - uy * trim}"
            marker-end="url(#bishoply-arrow-head)"
          />
        `;
      })
      .join("");

  const circles =
    annotationCircles
      .map((square) => {
        const center =
          getSquareCenterPercent(
            square
          );

        if (!center) {
          return "";
        }

        return `
          <circle
            class="annotation-circle"
            cx="${center.x}"
            cy="${center.y}"
            r="4.1"
          />
        `;
      })
      .join("");

  layer.innerHTML = `
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <marker
          id="bishoply-arrow-head"
          markerWidth="4"
          markerHeight="4"
          refX="3.3"
          refY="2"
          orient="auto"
          markerUnits="strokeWidth"
        >
          <path
            class="annotation-arrow-head"
            d="M0,0 L4,2 L0,4 Z"
          />
        </marker>
      </defs>

      ${arrows}
      ${circles}
    </svg>
  `;
}


function renderAnnotationControls() {
  if (isMobileOrIOS) {
    return;
  }

  const stage =
    boardElement.closest(
      ".board-stage"
    );

  if (!stage) {
    return;
  }

  let help =
    stage.querySelector(
      ".annotation-help"
    );

  if (!help) {
    help =
      document.createElement(
        "div"
      );

    help.className =
      "annotation-help";

    stage.appendChild(help);
  }

  help.innerHTML = `
    <span>
      Right-click a square for a circle ·
      Right-click + drag for an arrow
    </span>

    <button
      class="annotation-clear"
      type="button"
    >
      Clear markings
    </button>
  `;

  help
    .querySelector(
      ".annotation-clear"
    )
    .addEventListener(
      "click",
      clearAnnotations
    );
}


function removeAnnotationControls() {
  const stage =
    boardElement.closest(
      ".board-stage"
    );

  if (!stage) {
    return;
  }

  const help =
    stage.querySelector(
      ".annotation-help"
    );

  if (help) {
    help.remove();
  }

  const layer =
    boardElement.querySelector(
      ".annotation-layer"
    );

  if (layer) {
    layer.remove();
  }
}


function resetResignConfirmation() {
  resignConfirmationActive =
    false;

  if (
    resignConfirmationTimer
  ) {
    clearTimeout(
      resignConfirmationTimer
    );

    resignConfirmationTimer =
      null;
  }

  const button =
    $("#resign-game-button");

  if (button) {
    button.textContent =
      "Resign";

    button.disabled =
      false;
  }
}


async function resignCurrentGame() {
  if (
    !currentGame?.game_id ||
    !currentProfile?.discord_id ||
    currentGame.status !==
      "active"
  ) {
    return;
  }

  const button =
    $("#resign-game-button");

  if (
    !resignConfirmationActive
  ) {
    resignConfirmationActive =
      true;

    if (button) {
      button.textContent =
        "Confirm Resign";
    }

    setStatus(
      "Press Confirm Resign to forfeit the game."
    );

    resignConfirmationTimer =
      setTimeout(
        () => {
          resetResignConfirmation();

          setStatus(
            "Resignation cancelled."
          );
        },
        6000
      );

    return;
  }

  if (
    resignConfirmationTimer
  ) {
    clearTimeout(
      resignConfirmationTimer
    );

    resignConfirmationTimer =
      null;
  }

  resignConfirmationActive =
    false;

  if (button) {
    button.disabled =
      true;

    button.textContent =
      "Resigning...";
  }

  try {
    const game =
      await apiFetch(
        `/api/games/${currentGame.game_id}/resign`,
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body:
            JSON.stringify({
              discord_id:
                currentProfile.discord_id,
            }),
        }
      );

    await renderGame(game);

    await refreshProfile();

    await loadHistory();
  } catch (error) {
    resetResignConfirmation();

    throw error;
  }
}


function renderMatchPlayers(game) {
  const mine = getMyColor(game);
  const card = color => {
    const player = game[color];
    const name = player?.display_name || player?.username || "Waiting for opponent";
    const active = game.status === "active" && game.turn === color;
    const snapshot = game.competitive?.[color];
    const chessRating = player?.chess_rating ?? snapshot?.rating_after ?? game.rating?.[`${color}_before`];
    const sr = player?.sr ?? snapshot?.sr_after;
    let avatar = "";
    try {
      const url = new URL(player?.avatar_url);
      if (url.protocol === "https:") avatar = `<img src="${escapeHtml(url.href)}" alt="" referrerpolicy="no-referrer">`;
    } catch {}
    return `<div class="player-avatar">${avatar || (color === "white" ? "♙" : "♟")}</div><div class="player-identity"><span>${color === "white" ? "White" : "Black"}${mine === color ? " · You" : ""}</span><strong>${escapeHtml(name)}</strong><small>${chessRating != null ? `Chess Rating ${formatNumber(chessRating)}` : ""}${sr != null ? ` · Bishoply SR ${formatNumber(sr)}` : ""}</small></div><span class="player-turn ${active ? "is-turn" : ""}">${active ? "To move" : player ? (["white_win", "black_win", "draw"].includes(game.status) ? "Complete" : "Ready") : "Open seat"}</span>`;
  };
  $("#player-top").innerHTML = card(mine === "black" ? "white" : "black");
  $("#player-bottom").innerHTML = card(mine === "black" ? "black" : "white");
}


function renderGameInfo(game) {
  const myColor =
    getMyColor(game);

  const activePlayer =
    game.status === "active" &&
    Boolean(myColor);

  const finished = isEnded(game);
  const resultHtml = finished ? `<div class="ending-actions"><button class="gold-button" id="open-results">View Results</button>${LAUNCH_FEATURES.gameReview && ["white_win","black_win","draw"].includes(game.status) ? '<button class="dark-button" id="open-review">Review Game</button>' : ''}</div>` : "";

  const actions =
    activePlayer
      ? `
        <div class="game-action-row">
          <button
            id="resign-game-button"
            class="resign-button"
            type="button"
          >
            Resign
          </button>
        </div>
      `
      : "";

  renderMatchPlayers(game);
  gameInfo.innerHTML = `
    <div class="match-status" role="status">
      <span class="eyebrow gold">${finished ? "Match complete" : game.status === "waiting" ? "Awaiting challenger" : "In progress"}</span>
      <h3>${finished ? escapeHtml(getResultTitle(game)) : game.status === "waiting" ? "Your seat is ready" : `${game.turn === "white" ? "White" : "Black"} to move`}</h3>
      <p>${game.status === "waiting" ? "Share the game ID below with your opponent. The board will update when they join." : finished ? "Your result is ready. Explore the game at your own pace." : "Moves sync automatically."}</p>
    </div>
    ${actions}
    <details class="match-details" ${game.status === "waiting" ? "open" : ""}>
      <summary>Match details</summary>
      <span>Game ID</span><code>${escapeHtml(game.game_id)}</code>
      <button id="refresh-game-button" class="dark-button" type="button">Reconnect / refresh</button>
    </details>
    ${resultHtml}
  `;
  $("#open-results")?.addEventListener("click", () => gameResult.open());
  $("#open-review")?.addEventListener("click", () => gameReview.open());
  $("#refresh-game-button")?.addEventListener("click", () => loadGame(game.game_id).catch(error => setStatus(error.message)));

  const resignButton =
    $("#resign-game-button");

  if (resignButton) {
    resignButton.addEventListener(
      "click",
      async () => {
        try {
          await resignCurrentGame();
        } catch (error) {
          setStatus(
            `Bishoply error: ${error.message}`
          );
        }
      }
    );
  }
}


function renderMoves(moves) {
  if (!moves?.length) {
    movesList.innerHTML = `
      <div class="empty-mini">
        <strong>
          No moves yet.
        </strong>

        <span>
          White moves first.
        </span>
      </div>
    `;

    return;
  }

  movesList.innerHTML =
    moves
      .map(
        (move) => `
          <div class="move-item">
            <div>
              <strong>
                ${escapeHtml(move.move_number)}.
              </strong>

              <span>
                ${escapeHtml(move.color)}
              </span>
            </div>

            <code>
              ${escapeHtml(move.uci)}
            </code>

            <em>
              ${escapeHtml(move.san)}
            </em>
          </div>
        `
      )
      .join("");
}

function setPracticeStatus(message) {
  if (practiceStatusLine) {
    practiceStatusLine.textContent = message;
  }
}

function getPracticeColor(game = practiceGame) {
  return game?.player_color || practiceChoice.player_color || practicePlayerColor || "white";
}

function getPracticeBot(game = practiceGame) {
  return game?.bot || practiceBotRoster.find(bot => bot.bot_id === practiceChoice.bot_id) || null;
}

function decoratePracticeGame(game) {
  if (!game) {
    return game;
  }

  const bot = game.bot || getPracticeBot(game) || {};
  const player = {
    display_name: currentProfile?.display_name || currentProfile?.username || "You",
    username: currentProfile?.username || "you",
    avatar_url: currentProfile?.avatar_url || null,
    chess_rating: currentProfile?.rating ?? currentProfile?.chess_rating ?? null,
    sr: currentProfile?.sr ?? null,
  };
  const botPlayer = {
    display_name: bot.display_name || "Practice Bot",
    username: bot.bot_id || "practice-bot",
    avatar_url: bot.icon_path || null,
    chess_rating: bot.estimated_strength ?? null,
    sr: null,
  };

  return {
    ...game,
    bot,
    white: game.player_color === "white" ? player : botPlayer,
    black: game.player_color === "black" ? player : botPlayer,
  };
}

function renderPracticeColorToggle() {
  document.querySelectorAll("[data-practice-color]").forEach(button => {
    button.classList.toggle("active", button.dataset.practiceColor === practiceChoice.player_color);
  });
}

function selectPracticeColor(color) {
  practiceChoice.player_color = color === "black" ? "black" : "white";
  practicePlayerColor = practiceChoice.player_color;
  renderPracticeColorToggle();
  setPracticeStatus(`Training as ${practicePlayerColor}.`);
}

function practiceStatusTitle(game = practiceGame) {
  if (!game) return "Choose a bot to begin.";
  if (game.status === "active") {
    const bot = getPracticeBot(game);
    if (game.needs_bot_move && bot) {
      return `${bot.display_name} is thinking…`;
    }
    return game.turn === game.player_color ? "Your move" : "Waiting for the bot";
  }
  if (game.status === "draw") return "Practice game drawn.";
  return "Practice game complete.";
}

function formatPracticeEvaluation(evaluation) {
  if (!evaluation) {
    return { text: "—", fill: 50 };
  }

  const perspectiveSign = evaluation.perspective === "black" ? -1 : 1;
  if (evaluation.mate != null) {
    const mateScore = Number(evaluation.mate) * perspectiveSign;
    const mate = Math.max(1, Math.abs(mateScore) || 1);
    return {
      text: `${mateScore < 0 ? "−" : ""}M${mate}`,
      fill: mateScore > 0 ? 92 : 8,
    };
  }

  if (evaluation.win_probability != null || evaluation.white_outcome != null) {
    const rawOutcome = evaluation.win_probability != null ? Number(evaluation.win_probability) : Number(evaluation.white_outcome);
    const outcome = Math.max(0, Math.min(1, evaluation.perspective === "black" ? 1 - rawOutcome : rawOutcome));
    return {
      text: outcome === 0.5 ? "0.0" : `${outcome > 0.5 ? "+" : "−"}${Math.abs((outcome - 0.5) * 2).toFixed(1)}`,
      fill: Math.round(outcome * 100),
    };
  }

  if (evaluation.cp != null) {
    const cp = (Number(evaluation.cp) || 0) * perspectiveSign;
    const fill = Math.max(6, Math.min(94, 50 + cp / 12));
    return {
      text: `${cp > 0 ? "+" : cp < 0 ? "−" : ""}${Math.abs(cp / 100).toFixed(1)}`,
      fill,
    };
  }

  return { text: "—", fill: 50 };
}

function renderPracticeEvalBar() {
  if (!practiceEvalBar || !practiceEvalFill || !practiceEvalValue) {
    return;
  }

  const evaluation = practiceAnalysisState.evaluation || null;
  const value = formatPracticeEvaluation(evaluation);
  const pending = practiceAnalysisState.status === "queued" || practiceAnalysisState.status === "analyzing";
  const failed = practiceAnalysisState.status === "failed";
  const label = evaluation ? value.text : failed ? "Unavailable" : pending ? "Analyzing…" : "—";

  practiceEvalBar.hidden = !LAUNCH_FEATURES.liveEvaluation || !practiceEvalVisible;
  practiceEvalBar.classList.toggle("is-pending", pending && !evaluation);
  practiceEvalBar.classList.toggle("is-failed", failed && !evaluation);
  practiceEvalValue.textContent = label;
  practiceEvalFill.style.width = `${value.fill}%`;
}

function latestPracticePlayerMove(game = practiceGame) {
  return [...(game?.moves || [])].reverse().find(move => move.actor === "player") || null;
}

function getIntelligenceResult(result) {
  return result?.intelligence || null;
}

function intelligenceClassification(result) {
  const intelligence = getIntelligenceResult(result);
  return intelligence ? intelligence.move_quality?.classification || null : result?.classification || null;
}

function intelligenceEvaluation(result) {
  const intelligence = getIntelligenceResult(result);
  return intelligence ? intelligence.evaluation || null : result?.evaluation_after || (result?.white_outcome != null ? { white_outcome: result.white_outcome } : null);
}

function practiceClassificationIcon(classification) {
  return classificationUi(classification)?.icon || "";
}

function renderPracticeCandidates() {
  // Candidate evidence remains available to hints, review, and future Premium
  // coaching, but is intentionally hidden in free live Practice.
  if (practiceCandidates) {
    practiceCandidates.hidden = true;
    practiceCandidates.replaceChildren();
  }
}

function renderPracticeFeedback() {
  if (!practiceFeedback) {
    return;
  }

  const latestMove = latestPracticePlayerMove();
  const latestAnalysis = latestMove ? practiceMoveAnalysis.get(latestMove.ply) : null;
  const status = practiceAnalysisState.status;
  const pending = practicePendingAnalysis?.ply === latestMove?.ply && status !== "complete";
  const intelligence = getIntelligenceResult(latestAnalysis);
  const label = intelligenceClassification(latestAnalysis) || (latestAnalysis ? practiceAnalysisState.classification : null) || (pending ? "Analyzing…" : "Pending");
  const badge = classificationBadge(label);
  const displayBadge = LAUNCH_FEATURES.moveFeedback && label && label !== "Pending" ? badge : "";
  practiceFeedback.innerHTML = displayBadge ? `<div class="practice-feedback-head">${displayBadge}</div>` : "";
  practiceFeedback.hidden = !displayBadge;
}

function currentPracticeAnalysis() {
  const move = latestPracticePlayerMove();
  return move ? practiceMoveAnalysis.get(move.ply) || null : null;
}

function practiceCoachExplanation(analysis) {
  const label = analysis?.classification;
  const copy = {
    Best: "Strong choice. This keeps your advantage.",
    Excellent: "Very accurate. You preserved the position.",
    Good: "Solid move. There was a slightly stronger continuation.",
    Book: "This follows known opening theory.",
    Inaccuracy: "This gives up some of your advantage.",
    Mistake: "This changes the position significantly.",
    Miss: "There was a stronger tactical opportunity here.",
    Blunder: "This allows a major tactical swing.",
    Forced: "There was only one viable move.",
  };
  return copy[label] || "Bishoply is still analyzing this position.";
}

function showPracticeCoach(message, label = "Emma") {
  if (!practiceFeedback) return;
  const current = practiceFeedback.querySelector(".bishoply-classification-badge")?.textContent || label;
  practiceFeedback.querySelector("p")?.replaceChildren(document.createTextNode(message));
  const badge = practiceFeedback.querySelector(".bishoply-classification-badge");
  if (badge && !badge.textContent.trim()) badge.textContent = current;
}

function showPracticeBest() {
  const analysis = currentPracticeAnalysis();
  const best = analysis?.evidence?.best_candidate?.move || analysis?.best_move;
  if (!best) { showPracticeCoach("No verified best continuation is available yet."); return; }
  practiceHintState = {stage: 3, piece_square: best.slice(0, 2), destination: best.slice(2, 4), recommended_from: best.slice(0, 2), recommended_to: best.slice(2, 4), recommended_move: best};
  renderPracticeBoard();
  showPracticeCoach(`Best idea: ${best}. ${practiceCoachExplanation(analysis)}`);
}

function showPracticeWhy() {
  const analysis = currentPracticeAnalysis();
  showPracticeCoach(practiceCoachExplanation(analysis));
}

function showPracticeThreat() {
  const analysis = currentPracticeAnalysis();
  const threat = analysis?.evidence?.missed_opportunity?.pv?.[0];
  showPracticeCoach(threat ? `The position's clearest opportunity begins with ${threat}.` : "No clear tactical threat was detected.");
}

function speakPracticeCoach() {
  const text = practiceFeedback?.querySelector("p")?.textContent || practiceCoachExplanation(currentPracticeAnalysis());
  if (!emmaVoice.available()) { showPracticeCoach("Emma voice is not supported in this browser."); return; }
  emmaVoice.setEnabled(true);
  emmaVoice.speak(text);
}

function renderPracticePlayers(game = practiceGame) {
  if (!game || !practicePlayerTop || !practicePlayerBottom) {
    return;
  }

  const playerColor = getPracticeColor(game);
  const bot = getPracticeBot(game);
  const snapshot = game.competitive?.[playerColor];
  const player = {
    display_name: currentProfile?.display_name || currentProfile?.username || "You",
    username: currentProfile?.username || "you",
    avatar_url: currentProfile?.avatar_url,
    chess_rating: currentProfile?.rating ?? currentProfile?.chess_rating,
    sr: currentProfile?.sr,
  };
  const playerSide = playerColor;
  const botSide = playerColor === "white" ? "black" : "white";

  const card = (side, subject, badge, extra = "") => {
    let avatar = "";
    try {
      const url = new URL(subject?.avatar_url);
      if (url.protocol === "https:") avatar = `<img src="${escapeHtml(url.href)}" alt="" referrerpolicy="no-referrer">`;
    } catch {}
    const active = game.status === "active" && game.turn === side;
    const role = side === playerSide ? "You" : "Bot";
    return `
      <div class="player-avatar">${avatar || (side === "white" ? "♙" : "♟")}</div>
      <div class="player-identity">
        <span>${escapeHtml(role)} · ${side === "white" ? "White" : "Black"}</span>
        <strong>${escapeHtml(subject?.display_name || subject?.username || (side === playerSide ? "You" : bot?.display_name || "Practice Bot"))}</strong>
        <small>${extra}</small>
      </div>
      <span class="player-turn ${active ? "is-turn" : ""}">${active ? "To move" : game.status === "active" ? "Ready" : "Complete"}</span>
    `;
  };

  practicePlayerTop.innerHTML = card(
    "white",
    playerSide === "white" ? player : bot,
      playerSide === "white" ? "Player" : bot?.display_name || "Bot",
    playerSide === "white"
      ? `Chess Rating ${formatNumber(player.chess_rating)} · ${formatNumber(player.sr)} SR`
      : `Estimated Strength ${formatNumber(bot?.estimated_strength)} · ${escapeHtml(bot?.community_level || "")}`
  );

  practicePlayerBottom.innerHTML = card(
    "black",
    playerSide === "black" ? player : bot,
      playerSide === "black" ? "Player" : bot?.display_name || "Bot",
    playerSide === "black"
      ? `Chess Rating ${formatNumber(player.chess_rating)} · ${formatNumber(player.sr)} SR`
      : `Estimated Strength ${formatNumber(bot?.estimated_strength)} · ${escapeHtml(bot?.community_level || "")}`
  );
}

function renderPracticeInfo(game = practiceGame) {
  if (!practiceInfo) return;
  const bot = getPracticeBot(game);
  const status = game ? practiceStatusTitle(game) : "Choose a bot to begin.";
  const evaluation = practiceAnalysisState.evaluation ? formatPracticeEvaluation(practiceAnalysisState.evaluation).text : "Waiting";
  const analysisState = practiceAnalysisState.status === "failed"
    ? "Analysis failed"
    : practiceAnalysisState.status === "queued" || practiceAnalysisState.status === "analyzing"
      ? "Analysis pending"
      : practiceAnalysisState.status === "complete"
        ? "Ready"
        : "Waiting for your move";
  const summary = bot ? `
    <div class="practice-bot-summary">
      <div class="practice-bot-summary-icon">${bot.icon_path ? `<img src="${escapeHtml(bot.icon_path)}" alt="" loading="lazy">` : "♝"}</div>
      <div class="practice-bot-summary-copy">
        <span class="eyebrow gold">Selected opponent</span>
        <strong>${escapeHtml(bot.display_name)}</strong>
        <small>Estimated Bot Strength ${formatNumber(bot.estimated_strength)} · ${escapeHtml(bot.community_level || "Unknown")}</small>
        <p>${escapeHtml(bot.personality || "Practice bot")}</p>
      </div>
    </div>
  ` : "";
  practiceInfo.innerHTML = `
    ${summary}
    <div class="match-status" role="status">
      <span class="eyebrow gold">Practice / Unrated</span>
      <h3>${escapeHtml(status)}</h3>
      <p>${escapeHtml(game ? "Training in progress. Review stays available after the game ends." : "Pick a Bishoply bot to start training.")}</p>
      ${game?.bot_error ? `<p class="practice-error">${escapeHtml(game.bot_error)}</p>` : ""}
    </div>
    <div class="practice-info-grid">
      <div><span>Hints Used</span><strong>${formatNumber(game?.hint_count || 0)}</strong></div>
      <div><span>Assisted</span><strong>${game?.assisted ? "Yes" : "No"}</strong></div>
      <div><span>Evaluation</span><strong>${escapeHtml(evaluation)}</strong></div>
      <div><span>Analysis</span><strong>${escapeHtml(analysisState)}</strong></div>
    </div>
    <details class="match-details" ${game?.game_id ? "" : "open"}>
      <summary>Practice details</summary>
      <span>Game ID</span><code>${escapeHtml(game?.game_id || "—")}</code>
      <span>Mode</span><code>Practice / Unrated</code>
      <span>Bot personality</span><code>${escapeHtml(bot?.personality || "—")}</code>
      <button id="practice-refresh-button" class="dark-button" type="button">Refresh practice game</button>
    </details>
  `;
  $("#practice-refresh-button")?.addEventListener("click", () => syncPracticeGame().catch(error => setStatus(error.message)));
}

function renderPracticeMoves(game = practiceGame) {
  if (!practiceMovesList) return;
  const moves = [...(game?.moves || [])].reverse();
  if (!moves.length) {
    practiceMovesList.innerHTML = `
      <div class="empty-mini">
        <strong>No moves yet.</strong>
        <span>${game?.player_color === "black" ? "The bot opens first." : "White moves first."}</span>
      </div>
    `;
    return;
  }
  practiceMovesList.innerHTML = moves.map(move => {
    const analysis = practiceMoveAnalysis.get(move.ply);
    const pending = practicePendingAnalysis?.ply === move.ply && !intelligenceClassification(analysis);
    const label = intelligenceClassification(analysis) || (pending ? "Analyzing…" : move.actor === "bot" ? "Bot" : "Pending");
    const icon = practiceClassificationIcon(intelligenceClassification(analysis));
    return `
      <div class="move-item practice-move-item ${analysis ? "has-analysis" : ""} ${pending ? "is-pending" : ""}">
        <div>
          <strong>${escapeHtml(move.move_number)}.</strong>
          <span>${escapeHtml(move.color)} · ${escapeHtml(move.actor)}</span>
        </div>
        <code>${escapeHtml(move.uci)}</code>
        <em>${escapeHtml(move.san)}</em>
        <small>${analysis?.analysis_error ? "Analysis unavailable" : `${icon ? `${icon} ` : ""}${label}`}</small>
      </div>
    `;
  }).join("");
}

function applyPracticeHints() {
  if (!practiceBoardElement) return;
  practiceBoardElement.querySelector(".practice-hint-arrow-layer")?.remove();
  practiceBoardElement.classList.remove("practice-hint-stage-1", "practice-hint-stage-2", "practice-hint-stage-3");
  practiceBoardElement.querySelectorAll(".practice-hint-piece,.practice-hint-destination,.practice-hint-recommended").forEach(node => {
    node.classList.remove("practice-hint-piece", "practice-hint-destination", "practice-hint-recommended");
  });
  if (!practiceHintState) return;
  practiceBoardElement.classList.add(`practice-hint-stage-${practiceHintState.stage}`);
  const classes = [
    [practiceHintState.piece_square, "practice-hint-piece"],
    [practiceHintState.destination, "practice-hint-destination"],
    [practiceHintState.recommended_from, "practice-hint-recommended"],
    [practiceHintState.recommended_to, "practice-hint-recommended"],
  ];
  classes.forEach(([square, className]) => {
    if (!square) return;
    const element = practiceBoardElement.querySelector(`[data-square="${square}"]`);
    if (element) element.classList.add(className);
  });
  const arrow = practiceHintState?.stage >= 3 && practiceHintState.recommended_from && practiceHintState.recommended_to
    ? { from: practiceHintState.recommended_from, to: practiceHintState.recommended_to }
    : practiceSuggestionState;
  if (arrow?.from && arrow?.to) {
    const { squares } = getDisplaySquares(practiceGame, practicePlayerColor, false, practiceReviewFlipped);
    const center = square => {
      const index = squares.indexOf(square);
      return index < 0 ? null : { x: (index % 8) * 12.5 + 6.25, y: Math.floor(index / 8) * 12.5 + 6.25 };
    };
    const from = center(arrow.from);
    const to = center(arrow.to);
    if (from && to) {
      practiceBoardElement.insertAdjacentHTML("beforeend", `<svg class="practice-hint-arrow-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><defs><marker id="practice-hint-arrow-head" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 Z"></path></marker></defs><line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" marker-end="url(#practice-hint-arrow-head)"></line></svg>`);
    }
  }
}

function renderPracticeBoard() {
  if (!practiceBoardElement || !practiceGame?.fen) {
    if (practiceBoardElement) {
      practiceBoardElement.className = "board-empty";
      practiceBoardElement.innerHTML = `
        <div class="empty-board-card">
          <div class="empty-board-icon">♝</div>
          <h3>Practice Board</h3>
          <p>Choose a bot to load the training board.</p>
        </div>
      `;
    }
    return;
  }

  const view = renderBoardSurface(practiceBoardElement, practiceGame, {
    selectedSquare: practiceSelectedSquare,
    legalMoves: practiceLegalMoves,
    canMove: practiceCanMove,
    playerColor: practicePlayerColor,
    reviewPosition: practiceReviewPosition,
    reviewFlipped: practiceReviewFlipped,
  });
  practiceBoardPieces = view.boardPieces || {};
  bindBoardSquares(practiceBoardElement, practiceReview.active ? null : handlePracticeSquareClick);
  applyPracticeHints();
}

function renderPracticeEvalPreference() {
  if (practiceEvalToggle) {
    practiceEvalToggle.textContent = practiceEvalVisible ? "Eval bar on" : "Eval bar off";
    practiceEvalToggle.setAttribute("aria-pressed", String(practiceEvalVisible));
  }
  renderPracticeEvalBar();
}

function setPracticeEvaluation(evaluation, classification = null, message = null, kind = "pending") {
  practiceAnalysisState = {
    ...practiceAnalysisState,
    evaluation,
    classification: classification || practiceAnalysisState.classification,
    message: message || practiceAnalysisState.message,
    kind,
  };
  renderPracticeEvalBar();
}

function renderPracticeShell() {
  const hasGame = Boolean(practiceGame);
  [practiceBestButton, practiceWhyButton, practiceThreatButton, practiceSpeakButton].forEach(button => {
    if (button) button.hidden = !coachFeatures.advancedCoach;
  });
  if (practiceHintButton) practiceHintButton.hidden = !LAUNCH_FEATURES.liveHints;
  if (practiceEmmaVoiceButton) practiceEmmaVoiceButton.hidden = !LAUNCH_FEATURES.emmaVoice;
  if (practiceEvalToggle) practiceEvalToggle.hidden = !LAUNCH_FEATURES.liveEvaluation;
  if (practiceRestartButton) practiceRestartButton.hidden = practiceGame?.status === "active";
  if (practiceNewOpponentButton) practiceNewOpponentButton.hidden = practiceGame?.status === "active";
  if (practiceUndoButton) {
    const moveCount = practiceGame?.moves?.length || 0;
    practiceUndoButton.disabled = !practiceGame || practiceGame.status !== "active" || moveCount === 0 || practiceBusy;
  }
  renderPracticeView(hasGame ? "match" : "select");
  renderPracticeColorToggle();
  renderPracticeInfo();
  renderPracticePlayers();
  renderPracticeMoves();
  renderPracticeBoard();
  renderPracticeFeedback();
  renderPracticeEvalPreference();
  if (practiceModeLabel) {
    practiceModeLabel.textContent = hasGame ? "Practice / Unrated" : "Practice / Unrated";
  }
}

async function undoPracticeGame() {
  if (!practiceGame?.game_id || !canAccessPracticeGame() || practiceBusy) return;
  practiceBusy = true;
  practiceUndoButton && (practiceUndoButton.disabled = true);
  try {
    const game = await apiFetch(`/api/practice/games/${practiceGame.game_id}/undo`, {
      method: "POST", headers: practiceAuthHeaders(),
    });
    practiceGame = decoratePracticeGame(game);
    for (const ply of [...practiceMoveAnalysis.keys()]) {
      if (Number(ply) > Number(game.ply)) practiceMoveAnalysis.delete(ply);
    }
    practicePendingAnalysis = null;
    practiceAnalysisState = { status: "idle", message: "Analysis pending", classification: null };
    clearPracticeHints();
    await renderPracticeGame(practiceGame);
  } finally {
    practiceBusy = false;
    renderPracticeShell();
  }
}

function setPracticeMoveState() {
  practiceCanMove = Boolean(practiceGame && practiceGame.status === "active" && practiceGame.turn === practicePlayerColor);
}

async function loadPracticeBots() {
  if (!practiceBots || !appReady) return;
  practiceBots.textContent = "Loading bots...";
  try {
    const data = await apiFetch("/api/practice/bots");
    practiceBotRoster = data.bots || [];
    if (!practiceChoice.bot_id && practiceBotRoster.length) {
      practiceChoice.bot_id = practiceBotRoster[0].bot_id;
    }
    practiceBots.innerHTML = practiceBotRoster.map(bot => {
      const selected = bot.bot_id === practiceChoice.bot_id;
      const blocked = practiceGame?.status === "active";
      return `
        <article class="practice-bot-card ${selected ? "selected" : ""}" data-practice-bot="${escapeHtml(bot.bot_id)}">
          <div class="practice-bot-icon"><img src="${escapeHtml(bot.icon_path)}" alt="" loading="lazy"></div>
          <div class="practice-bot-copy">
            <span class="eyebrow gold">${escapeHtml(bot.community_level)}</span>
            <h3>${escapeHtml(bot.display_name)}</h3>
            <strong>Estimated Bot Strength ${formatNumber(bot.estimated_strength)}</strong>
            <p>${escapeHtml(bot.personality)}</p>
          </div>
          <button class="gold-button full" type="button" data-start-practice="${escapeHtml(bot.bot_id)}" ${blocked ? "disabled" : ""}>Start Practice</button>
        </article>
      `;
    }).join("");
    practiceBots.querySelectorAll("[data-start-practice]").forEach(button => {
      button.addEventListener("click", async () => {
        practiceDebug("start handler fired", {
          bot_id: button.dataset.startPractice || "",
          player_color: practiceChoice.player_color,
        });
        try {
          await createPracticeGame(button.dataset.startPractice, practiceChoice.player_color);
        } catch (error) {
          practiceDebug("create failed", {
            status: error?.status || 0,
            kind: error?.kind || "request_error",
            message: error?.message || "",
          });
          practiceCreateBusy = false;
          renderPracticeView("select");
          setPracticeStatus(`Practice error: ${error.message}`);
        }
      });
    });
    renderPracticeColorToggle();
  } catch (error) {
    practiceBots.innerHTML = `
      <div class="empty-mini">
        <strong>Practice bots unavailable.</strong>
        <span>Refresh the page and try again.</span>
      </div>
    `;
    setPracticeStatus("Practice bots could not be loaded.");
  }
}

async function recoverActivePractice() {
  if (!currentProfile) return false;
  try {
    const active = await apiFetch("/api/practice/active");
    if (!active?.active || !active.game_id) return false;
    const game = active.game || await apiFetch(`/api/practice/games/${active.game_id}`, { headers: practiceAuthHeaders() });
    practiceAccessKey = null;
    practiceGame = decoratePracticeGame(game);
    await renderPracticeGame(practiceGame);
    if (practiceGame.needs_bot_move) await startPracticeBotIfNeeded();
    setPracticeStatus(`Practice resumed against ${getPracticeBot(practiceGame)?.display_name || "the bot"}.`);
    return true;
  } catch (error) {
    if (import.meta.env?.DEV) console.debug("[Bishoply Startup] active Practice recovery skipped", { status: error?.status || 0 });
    return false;
  }
}

async function startPracticeBotIfNeeded() {
  if (!practiceGame?.game_id || practiceGame.status !== "active" || !practiceGame.needs_bot_move || practiceBotBusy) {
    return;
  }

  practiceBotBusy = true;
  setPracticeStatus(`${getPracticeBot()?.display_name || "The bot"} is thinking…`);
  renderPracticeInfo();
  try {
    const data = await apiFetch(`/api/practice/games/${practiceGame.game_id}/bot-move`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...practiceAuthHeaders(),
      },
      body: JSON.stringify({ expected_ply: practiceGame.ply }),
    });
    practiceGame = data;
    await renderPracticeGame(data);
    setPracticeStatus(practiceStatusTitle(data));
    if (data.status === "active" && data.needs_bot_move) {
      await startPracticeBotIfNeeded();
    }
  } catch (error) {
    practiceGame.bot_error = "Bot unavailable or timed out; retry bot response";
    renderPracticeGame(practiceGame);
    setPracticeStatus("Bot timed out. Retry the move or start a new game.");
  } finally {
    practiceBotBusy = false;
  }
}

function parseAnalysisMove(data, ply) {
  const result = data?.result;
  const moves = Array.isArray(result?.moves) ? result.moves : result && result.ply != null ? [result] : [];
  if (ply != null) {
    return moves.find(move => Number(move.ply) === Number(ply)) || null;
  }
  return moves.at(-1) || null;
}

async function requestPracticeAnalysis(ply, start = false) {
  if (!practiceGame?.game_id || !canAccessPracticeGame()) return;
  try {
    const data = await apiFetch(`/api/practice/games/${practiceGame.game_id}/analysis/${ply}`, {
      method: start ? "POST" : "GET",
      headers: practiceAuthHeaders(),
    });
    practicePendingAnalysis = { ply, status: data.status };
    if (data.result) {
      const move = parseAnalysisMove(data, ply);
      if (move) {
        practiceMoveAnalysis.set(ply, move);
        const intelligence = getIntelligenceResult(move);
        if (intelligence) console.debug("[Bishoply] Intelligence V1 active");
        practiceAnalysisState.intelligence = intelligence;
        practiceAnalysisState.evaluation = intelligenceEvaluation(move) || practiceAnalysisState.evaluation;
        practiceAnalysisState.classification = intelligenceClassification(move) || practiceAnalysisState.classification;
        const coach = intelligence?.coach;
        practiceAnalysisState.message = move.analysis_error || (coach?.should_comment && coach.message) || (practiceAnalysisState.classification ? `${practiceAnalysisState.classification} · ${move.san}` : "Analysis pending.");
        practiceAnalysisState.kind = ["Best", "Excellent", "Good", "Book", "Forced"].includes(practiceAnalysisState.classification) ? "positive" :
          ["Inaccuracy", "Mistake", "Miss"].includes(practiceAnalysisState.classification) ? "mistake" :
          practiceAnalysisState.classification === "Blunder" ? "blunder" : "pending";
        renderPracticeCandidates();
        if (intelligence?.hint && practiceHintState) updatePracticeHintFromResponse({ ...intelligence.hint, stage: practiceHintState.stage });
        const speechKey = coach?.message_key || `${practiceGame.game_id}:${ply}:${coach?.message || ""}`;
        const meaningful = ["Best", "Excellent", "Mistake", "Miss", "Blunder"].includes(practiceAnalysisState.classification)
          || ["high", "critical"].includes(String(coach?.priority || "").toLowerCase());
        const canSpeak = Boolean(LAUNCH_FEATURES.emmaCoach && LAUNCH_FEATURES.emmaVoice && (coach?.should_speak || meaningful) && emmaVoice.enabled && coach.message && (emmaVoice.available() || emmaVoice.remoteSpeak) && emmaVoice.unlocked);
        if (import.meta.env?.DEV) console.debug("[Bishoply Emma Voice]", { game_id: practiceGame.game_id, ply, should_speak: Boolean(coach?.should_speak), enabled: emmaVoice.enabled, unlocked: emmaVoice.unlocked, speechSynthesis_available: emmaVoice.available(), voices_count: emmaVoice.voices?.length || 0, selected_voice: emmaVoice.preferredVoice()?.name || "none", message: coach?.message || "", action: canSpeak ? "eligible" : "skipped", error: "" });
        if (canSpeak && practiceSpokenKey !== speechKey && !practiceSpokenKeys.has(speechKey)) {
          practiceSpokenKey = speechKey;
          practiceSpokenKeys.add(speechKey);
          const spoken = emmaVoice.speak(coach.message);
          if (import.meta.env?.DEV) console.debug("[Bishoply Emma]", { available: true, enabled: true, shouldSpeak: true, voice: emmaVoice.preferredVoice()?.name || "default", messageKey: speechKey, action: spoken ? "spoken" : "skipped", reason: spoken ? "" : "voice manager rejected" });
        } else if (import.meta.env?.DEV) {
          console.debug("[Bishoply Emma]", { available: emmaVoice.available(), enabled: emmaVoice.enabled, shouldSpeak: Boolean(coach?.should_speak), voice: emmaVoice.preferredVoice()?.name || "none", messageKey: speechKey, action: "skipped", reason: !coach?.message ? "blank message" : practiceSpokenKey === speechKey ? "duplicate" : !emmaVoice.enabled ? "disabled" : "unavailable" });
        }
        practiceAnalysisState.assisted = Boolean(practiceGame?.assisted);
        if (data.status === "complete") {
          practicePendingAnalysis = null;
        }
        if (practiceAnalysisState.kind && practiceAnalysisState.kind !== "pending" && practiceAnnouncedPly !== ply) {
          practiceAnnouncedPly = ply;
          chessSound.play(practiceAnalysisState.kind === "positive" ? "positive" : practiceAnalysisState.kind);
        }
      }
    }
    practiceAnalysisState.status = data.status;
    if (data.status === "complete") {
      if (practiceAnalysisTimer) {
        clearTimeout(practiceAnalysisTimer);
        practiceAnalysisTimer = null;
      }
      practiceAnalysisState.message = "";
      practicePendingAnalysis = null;
    } else if (data.status === "failed") {
      if (practiceAnalysisTimer) {
        clearTimeout(practiceAnalysisTimer);
        practiceAnalysisTimer = null;
      }
      practiceAnalysisState.message = data.error || "Analysis failed.";
      practiceAnalysisState.classification = intelligenceClassification(practiceMoveAnalysis.get(ply)) || null;
    } else {
      practiceAnalysisState.message = "Analysis pending.";
      practiceAnalysisState.classification = intelligenceClassification(practiceMoveAnalysis.get(ply)) || null;
      if (practiceAnalysisTimer) {
        clearTimeout(practiceAnalysisTimer);
      }
      practiceAnalysisTimer = setTimeout(() => {
        requestPracticeAnalysis(ply, false).catch(() => {});
      }, document.hidden ? 5000 : 1800);
    }
    renderPracticeFeedback();
    renderPracticeMoves();
    renderPracticeEvalBar();
  } catch (error) {
    practiceAnalysisState.status = "failed";
    practiceAnalysisState.message = "Analysis failed.";
    practicePendingAnalysis = { ply, status: "failed" };
    renderPracticeFeedback();
    renderPracticeMoves();
    renderPracticeEvalBar();
  }
}

function updatePracticeHintFromResponse(data) {
  if (!data) return;
  const hint = data.hint || data;
  practiceHintState = {
    stage: data.stage || 3,
    piece_square: hint.source_square || hint.piece_square,
    destination: hint.target_square || hint.destination || null,
    recommended_from: hint.source_square || hint.piece_square || null,
    recommended_to: hint.target_square || hint.destination || null,
    recommended_move: hint.move_uci || hint.recommended_move || null,
    san: hint.move_san || hint.san || null,
  };
  renderPracticeBoard();
  renderPracticeFeedback();
}

function clearPracticeHints() {
  practiceHintState = null;
  practiceSuggestionState = null;
  if (practiceBoardElement) {
    practiceBoardElement.classList.remove("practice-hint-stage-1", "practice-hint-stage-2", "practice-hint-stage-3");
    practiceBoardElement.querySelector(".practice-hint-arrow-layer")?.remove();
  }
}

async function requestPracticeHint(stage) {
  if (!practiceGame?.game_id || !canAccessPracticeGame()) return;
  const data = await apiFetch(`/api/practice/games/${practiceGame.game_id}/hint`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...practiceAuthHeaders(),
    },
    body: JSON.stringify({ expected_ply: practiceGame.ply, stage }),
  });
  practiceGame = await apiFetch(`/api/practice/games/${practiceGame.game_id}`, {
    headers: practiceAuthHeaders(),
  });
  practiceGame = decoratePracticeGame(practiceGame);
  setPracticeMoveState();
  updatePracticeHintFromResponse(data);
  // Hint is an internal board update; never invoke the full Practice shell
  // renderer because that also owns top-level view/scroll transitions.
  renderPracticeInfo(practiceGame);
  renderPracticeMoves(practiceGame);
}

async function submitPracticeMove(uci) {
  if (!practiceGame?.game_id || !canAccessPracticeGame() || practiceBusy || !practiceCanMove) return;
  practiceBusy = true;
  selectedSquare = null;
  practiceSelectedSquare = null;
  clearPracticeHints();
  practiceBoardElement?.classList.add("board-thinking");
  try {
    const data = await apiFetch(`/api/practice/games/${practiceGame.game_id}/move`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...practiceAuthHeaders(),
      },
      body: JSON.stringify({ move: uci, expected_ply: practiceGame.ply }),
    });
    practiceGame = data;
    await renderPracticeGame(data);
    await requestPracticeAnalysis(data.analysis?.ply || data.ply, true);
    if (data.status === "active" && data.needs_bot_move) {
      await startPracticeBotIfNeeded();
    }
    await refreshProfile();
    await loadHistory();
  } finally {
    practiceBusy = false;
    practiceBoardElement?.classList.remove("board-thinking");
  }
}

function selectPracticeSquare(square) {
  const available = practiceLegalMoves.filter(move => move.from === square);
  if (!available.length) {
    practiceSelectedSquare = null;
    renderPracticeBoard();
    return;
  }
  practiceSelectedSquare = square;
  renderPracticeBoard();
  setPracticeStatus(`Selected ${square}. Choose a destination.`);
}

async function handlePracticeSquareClick(square) {
  emmaVoice.unlock();
  if (practiceReview.active) return;
  if (!practiceGame) return;
  if (practiceGame.status !== "active") {
    setPracticeStatus("Practice game is complete.");
    return;
  }
  if (!practiceCanMove) {
    setPracticeStatus("Waiting for the bot.");
    return;
  }

  const piece = practiceBoardPieces[square];
  if (practiceSelectedSquare) {
    const destinationMoves = practiceLegalMoves.filter(move => move.from === practiceSelectedSquare && move.to === square);
    if (destinationMoves.length) {
      const queen = destinationMoves.find(move => move.promotion === "queen");
      await submitPracticeMove((queen || destinationMoves[0]).uci);
      return;
    }
    if (piece && piece.color === practicePlayerColor) {
      selectPracticeSquare(square);
      return;
    }
    practiceSelectedSquare = null;
    renderPracticeBoard();
    return;
  }

  if (piece && piece.color === practicePlayerColor) {
    selectPracticeSquare(square);
  }
}

async function createPracticeGame(botId, color = practiceChoice.player_color) {
  const ready = appReady && Boolean(currentProfile);
  practiceDebug("readiness", { ready, app_ready: appReady, has_profile: Boolean(currentProfile), web_session: webSessionAuthenticated });
  if (!requireReady()) return;
  if (practiceCreateBusy) return;
  if (!botId) {
    setPracticeStatus("Select a bot first.");
    return;
  }
  practiceCreateBusy = true;
  practiceChoice.bot_id = botId;
  practiceChoice.player_color = color === "black" ? "black" : "white";
  practicePlayerColor = practiceChoice.player_color;
  const launchCopy = { scout:"Scouting the position…", tempo:"Finding the rhythm…", fork:"Looking for tactics…", gambit:"Preparing an attack…", castle:"Fortifying the board…", tactician:"Calculating tactics…", endgame:"Preparing for the long game…", vanguard:"Taking the initiative…", maestro:"Composing the position…", crown:"Your strongest opponent awaits." };
  const selectedBot = getPracticeBot() || practiceBotRoster.find(bot => bot.bot_id === botId) || {};
  setPracticeStatus(`${selectedBot.display_name || botId} · ${launchCopy[botId] || "Preparing the board…"}`);
  renderPracticeView("loading");
  if (practiceLoadingBot) practiceLoadingBot.textContent = selectedBot.display_name || botId;
  if (practiceLoadingStrength) practiceLoadingStrength.textContent = `Estimated Bot Strength ${formatNumber(selectedBot.estimated_strength)}`;
  if (practiceLoadingCopy) practiceLoadingCopy.textContent = launchCopy[botId] || "Preparing the board…";
  practiceDebug("create request", {
    bot_id: botId,
    player_color: practiceChoice.player_color,
    path: "/api/practice/games",
  });
  const game = await apiFetch("/api/practice/games", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(discordAccessToken ? { Authorization: `Bearer ${discordAccessToken}` } : {}),
    },
    body: JSON.stringify({
      ...(currentProfile?.discord_id ? { discord_id: currentProfile.discord_id } : {}),
      bot_id: botId,
      player_color: practiceChoice.player_color,
      }),
  });
  practiceDebug("create response", { game_id: game?.game_id || "", status: game?.status || "" });
  practiceCreateBusy = false;
  const { access_key, ...practiceGameData } = game;
  practiceAccessKey = access_key;
  practiceGame = decoratePracticeGame(practiceGameData);
  practiceReview.close();
  practiceReviewPosition = null;
  practiceReviewFlipped = false;
  clearPracticeHints();
  practiceMoveAnalysis = new Map();
  practiceAnnouncedPly = null;
  practiceSpokenKey = null;
  practiceSpokenKeys.clear();
  if (practiceAnalysisTimer) {
    clearTimeout(practiceAnalysisTimer);
    practiceAnalysisTimer = null;
  }
  practiceAnalysisState = { status: "idle", message: "Analysis pending", classification: null };
  setPracticeStatus(`Practice started against ${game.bot.display_name}.`);
  await renderPracticeGame(practiceGame);
  practiceDebug("game transition", { game_id: practiceGame?.game_id || "", view: "match" });
  if (game.needs_bot_move) {
    await startPracticeBotIfNeeded();
  }
}

async function restartPracticeGame() {
  if (!practiceChoice.bot_id) {
    setPracticeStatus("Choose a bot first.");
    return;
  }
  if (practiceGame?.status === "active") {
    setPracticeStatus("Resign or finish the current game before restarting.");
    return;
  }
  await createPracticeGame(practiceChoice.bot_id, practiceChoice.player_color);
}

async function resignPracticeGame() {
  if (!practiceGame?.game_id || !practiceAccessKey) return;
  const game = await apiFetch(`/api/practice/games/${practiceGame.game_id}/resign`, {
    method: "POST",
    headers: { "X-Practice-Key": practiceAccessKey },
  });
  practiceGame = decoratePracticeGame(game);
  await renderPracticeGame(practiceGame);
  gameResult.load(practiceGame, getPracticeColor(practiceGame), () => practiceReview.open());
  await refreshProfile();
  await loadHistory();
}

async function syncPracticeGame() {
  if (!practiceGame?.game_id || !practiceAccessKey) return;
  const game = await apiFetch(`/api/practice/games/${practiceGame.game_id}`, {
    headers: { "X-Practice-Key": practiceAccessKey },
  });
  practiceGame = decoratePracticeGame(game);
  await renderPracticeGame(game);
}

async function renderPracticeGame(game) {
  practiceGame = decoratePracticeGame(game);
  practicePlayerColor = getPracticeColor(game);
  if (game.status === "active" && game.turn === game.player_color) {
    practiceLegalMoves = game.legal_moves || [];
    practiceCanMove = true;
  } else {
    practiceLegalMoves = [];
    practiceCanMove = false;
  }
  setPracticeMoveState();
  if (practiceGame?.bot_id) {
    practiceChoice.bot_id = practiceGame.bot_id;
  }
  renderPracticeShell();
  practiceReview.load(practiceGame, getPracticeColor(practiceGame), () => practiceReview.open());
  gameResult.load(practiceGame, getPracticeColor(practiceGame), () => practiceReview.open());
  if (game.status === "active" && game.needs_bot_move) {
    setPracticeStatus(`${getPracticeBot(game)?.display_name || "The bot"} is thinking…`);
  } else if (game.status !== "active") {
    setPracticeStatus(practiceStatusTitle(game));
  }
  renderPracticePlayers(game);
  renderPracticeInfo(game);
  renderPracticeMoves(game);
  renderPracticeBoard();
  renderPracticeFeedback();
  renderPracticeEvalBar();
}


async function handleFinishedGame(game) {
  if (
    !game?.game_id ||
    handledFinishedGames.has(
      game.game_id
    )
  ) {
    return;
  }

  if (
    game.status === "active" ||
    game.status === "waiting"
  ) {
    return;
  }

  handledFinishedGames.add(
    game.game_id
  );

  await refreshProfile();

  await loadHistory();

  const result =
    getMyResult(game);

  const rated =
    game.competitive?.decision ===
    "approved";

  if (result === "win") {
    setStatus(
      rated
        ? "Victory · Rated game complete."
        : "Victory · Unrated game complete."
    );

  } else if (
    result === "loss"
  ) {
    setStatus(
      rated
        ? "Defeat · Rated game complete."
        : "Defeat · Unrated game complete."
    );

  } else if (
    result === "draw"
  ) {
    setStatus(
      rated
        ? "Draw · Rated game complete."
        : "Draw · Unrated game complete."
    );
  }
}


async function renderGame(game) {
  chessSound.transition(currentGame, game, getMyColor(game));
  if (currentGame?.game_id !== game.game_id) reviewPosition = null;
  currentGame =
    game;

  selectedSquare =
    null;

  if (joinGameInput) {
    joinGameInput.value =
      game.game_id;
  }

  gameReview.load(game);
  renderGameInfo(game);
  gameResult.load(game, getMyColor(game), () => gameReview.open());

  renderMoves(
    game.moves || []
  );

  renderBoard();

  await loadLegalMoves();

  await handleFinishedGame(
    game
  );
}


async function refreshProfile() {
  if (!currentProfile) {
    return;
  }

  currentProfile =
    await apiFetch(currentProfile.discord_id
      ? `/api/profile/${currentProfile.discord_id}`
      : "/api/profile");

  renderProfile(
    currentProfile
  );
  await loadAccountConnections();
  await loadProfileCosmetics();
}

async function loadAccountConnections() {
  if (!accountConnections || !currentProfile) return;
  try {
    const data = await apiFetch("/api/auth/connections");
    const connected = new Set((data.connections || []).map((item) => item.provider));
    accountConnections.hidden = false;
    accountConnections.innerHTML = `<strong>Connections</strong><span>${["discord", "google", "apple"].map((provider) => `${provider[0].toUpperCase()}${provider.slice(1)} · ${connected.has(provider) ? "Connected" : "Not connected"}`).join("<br>")}</span>`;
  } catch { accountConnections.hidden = true; }
}


async function loadHistory() {
  if (!currentProfile) {
    return;
  }

  const historyRequests = [apiFetch("/api/practice/history?limit=20")];
  if (currentProfile.discord_id) {
    historyRequests.push(apiFetch(`/api/games/history/${currentProfile.discord_id}?limit=20`));
  }
  const historyResults = await Promise.allSettled(historyRequests);
  const data = {
    games: historyResults.flatMap((result) => result.status === "fulfilled" ? (result.value.games || []) : [])
  };

  if (!historyList) {
    return;
  }

  if (!data.games.length) {
    historyList.innerHTML = `
      <div class="empty-mini">
        <strong>
          No games yet.
        </strong>

        <span>
          Create your first duel.
        </span>
      </div>
    `;

    return;
  }

  historyList.innerHTML =
    data.games
      .map((game) => {
        const opponent = game.opponent?.display_name || game.opponent?.username ||
          (game.user_color === "white"
            ? (game.black?.display_name || game.black?.username || "Waiting")
            : (game.white?.display_name || game.white?.username || "Waiting"));

        let status =
          game.user_result;

        if (
          status === "in_progress"
        ) {
          status =
            "In progress";
        }

        if (
          status === "waiting"
        ) {
          status =
            "Waiting";
        }

        const rated =
          game.competitive_decision ===
          "approved";

        const finished =
          ![
            "active",
            "waiting",
          ].includes(
            game.status
          );

        const ratingChange =
          game.rating_change;

        const srChange =
          game.sr_change;

        const resultReason = game.termination_reason ? game.termination_reason.replaceAll("_", " ") : "";
        const dateLabel = game.updated_at ? new Date(game.updated_at).toLocaleDateString() : "";
        let changeHtml = "";

        if (
          finished &&
          rated
        ) {
          const ratingText = ratingChange == null ? "—" : signedNumber(ratingChange);
          const srText = game.sr_change == null ? "—" : signedNumber(game.sr_change);
          changeHtml = `
            <span>
              ${ratingText} Rating · ${srText} SR
            </span>
          `;
        }

        if (
          finished &&
          !rated
        ) {
          changeHtml = `
            <span>
              Unrated
            </span>
          `;
        }

        return `
          <button
            class="history-item"
            data-game-id="${escapeHtml(game.game_id)}"
            type="button"
          >
            <div>
              <strong>
                ${escapeHtml(status)}
              </strong>

              <span>
                ${escapeHtml(game.user_color)}
                vs
                ${escapeHtml(opponent)}
                ${dateLabel ? ` · ${escapeHtml(dateLabel)}` : ""}
              </span>
              ${resultReason ? `<small>${escapeHtml(resultReason)}</small>` : ""}
            </div>

            <div>
              ${changeHtml}

              <span>
                ${formatNumber(game.move_count)}
                moves
              </span>
            </div>
          </button>
        `;
      })
      .join("");

  $$(".history-item")
    .forEach(
      (button) => {
        button.addEventListener(
          "click",
          async () => {
            showPage("game");

            await loadGame(
              button.dataset.gameId
            );
          }
        );
      }
    );
}

async function loadLeaderboard() {
  if (!leaderboardList) return;
  leaderboardList.textContent = "Loading leaderboard…";
  try {
    const data = await apiFetch(`/api/leaderboard?kind=${leaderboardKind}&limit=50&offset=0`);
    const field = leaderboardKind === "sr" ? "sr" : "chess_rating";
    leaderboardList.innerHTML = data.entries.length ? data.entries.map(entry => `<div class="history-item leaderboard-row"><div><strong>#${entry.rank} · ${escapeHtml(entry.display_name)}</strong><span>${entry.games_played != null ? `${entry.games_played} games` : "Bishoply progression"}</span></div><strong>${formatNumber(entry[field])} ${leaderboardKind === "sr" ? "SR" : "Rating"}</strong></div>`).join("") : `<div class="empty-mini"><strong>No ranked players yet.</strong><span>Play a Duel to appear here.</span></div>`;
    if (data.your_rank && !data.entries.some(entry => entry.rank === data.your_rank.rank)) leaderboardList.insertAdjacentHTML("beforeend", `<div class="history-item leaderboard-row is-current"><div><strong>Your rank</strong><span>#${data.your_rank.rank}</span></div><strong>${formatNumber(data.your_rank[field])} ${leaderboardKind === "sr" ? "SR" : "Rating"}</strong></div>`);
  } catch (error) { leaderboardList.textContent = "Leaderboard could not be loaded."; }
}


function requireReady() {
  if (
    !appReady ||
    !currentProfile?.discord_id
  ) {
    setStatus(
      "Bishoply is still connecting."
    );

    return false;
  }

  return true;
}


async function createGame() {
  if (!requireReady()) {
    return;
  }

  setStatus(
    "Creating duel..."
  );

  const match =
    await apiFetch(
      "/api/games/casual",
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json",
        },

        body:
          JSON.stringify({
            discord_id:
              currentProfile.discord_id,
          }),
      }
    );

  const game = await apiFetch(`/api/games/${match.game_id}`);
  annotationArrows = [];
  annotationCircles = [];

  await renderGame(game);

  await loadHistory();

  showPage("game");

  setStatus(
    "Game created. Share the Game ID with your opponent."
  );
}

async function findDuel() {
  if (!requireReady() || matchmakingTimer) return;
  if (matchmakingStatus) matchmakingStatus.textContent = "Finding an opponent…";
  createGameButton && (createGameButton.disabled = true);
  cancelMatchmakingButton && (cancelMatchmakingButton.hidden = false);
  const state = await apiFetch("/api/matchmaking/duel/join", { method: "POST" });
  if (state.status === "matched" || state.status === "active_game") return openMatchedDuel(state);
  const poll = async () => {
    if (matchmakingPolling) return;
    matchmakingPolling = true;
    try {
      const next = await apiFetch("/api/matchmaking/duel/status");
      if (next.status === "matched" || next.status === "active_game") return openMatchedDuel(next);
      if (matchmakingStatus) matchmakingStatus.textContent = `Finding an opponent… Searching ±${next.rating_window || 150}`;
    } catch (error) { setStatus(`Bishoply error: ${error.message}`); }
    finally { matchmakingPolling = false; }
  };
  matchmakingTimer = window.setInterval(poll, 2000);
  await poll();
}

async function cancelDuelSearch() {
  if (matchmakingTimer) { clearInterval(matchmakingTimer); matchmakingTimer = null; }
  await apiFetch("/api/matchmaking/duel/cancel", { method: "POST" });
  if (matchmakingStatus) matchmakingStatus.textContent = "Search cancelled.";
  if (createGameButton) { createGameButton.disabled = false; createGameButton.textContent = "Find Opponent"; }
  if (cancelMatchmakingButton) cancelMatchmakingButton.hidden = true;
}

async function openMatchedDuel(state) {
  if (matchmakingTimer) { clearInterval(matchmakingTimer); matchmakingTimer = null; }
  if (matchmakingStatus) matchmakingStatus.textContent = "Opponent found.";
  const game = await apiFetch(`/api/games/${state.game_id}`);
  await renderGame(game);
  showPage("game");
  createGameButton && (createGameButton.disabled = false);
  if (cancelMatchmakingButton) cancelMatchmakingButton.hidden = true;
}


async function joinGame() {
  if (!requireReady()) {
    return;
  }

  const gameId =
    joinGameInput
      ?.value
      ?.trim();

  if (!gameId) {
    setStatus(
      "Paste a Game ID first."
    );

    return;
  }

  setStatus(
    "Joining duel..."
  );

  const match =
    await apiFetch(
      `/api/games/${gameId}/join`,
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json",
        },

        body:
          JSON.stringify({
            discord_id:
              currentProfile.discord_id,
          }),
      }
    );

  const game = await apiFetch(`/api/games/${match.game_id}`);
  annotationArrows = [];
  annotationCircles = [];

  await renderGame(game);

  await loadHistory();

  showPage("game");

  setStatus(
    "Duel joined."
  );
}


async function loadGame(
  gameId,
  silent = false
) {
  if (!gameId) {
    renderEmptyGame();

    return;
  }

  if (!silent) {
    setStatus(
      "Refreshing duel..."
    );
  }

  const game =
    await apiFetch(
      `/api/games/${gameId}`
    );

  await renderGame(game);
}


async function syncCurrentGame() {
  if (
    syncBusy ||
    !currentGame?.game_id ||
    !appReady
  ) {
    return;
  }

  const gamePage =
    $("#page-game");

  if (
    !gamePage?.classList.contains(
      "active"
    )
  ) {
    return;
  }

  syncBusy = true;

  try {
    const latest =
      await apiFetch(
        `/api/games/${currentGame.game_id}`
      );

    const changed =
      latest.fen !==
        currentGame.fen ||

      latest.status !==
        currentGame.status ||

      latest.integrity_status !==
        currentGame.integrity_status ||

      latest.rating_processed !==
        currentGame.rating_processed ||

      (
        latest.moves?.length ||
        0
      ) !==
      (
        currentGame.moves?.length ||
        0
      ) ||

      String(
        latest.black?.discord_id ||
        ""
      ) !==
      String(
        currentGame.black?.discord_id ||
        ""
      );

    if (changed) {
      await renderGame(
        latest
      );
    }
  } catch (error) {
    console.error(
      "Game sync failed:",
      error
    );
  } finally {
    syncBusy = false;
  }
}


function startGameSync() {
  if (syncTimer) {
    clearInterval(
      syncTimer
    );
  }

  syncTimer =
    setInterval(
      syncCurrentGame,
      1500
    );
}

window.addEventListener("offline", () => setStatus("Connection lost. We're trying to reconnect."));
window.addEventListener("online", () => setStatus("Connection restored."));


function bindEvents() {
  if (accountLogoutButton) accountLogoutButton.addEventListener("click", async () => {
    const csrf = document.cookie.split("; ").find((item) => item.startsWith("bishoply_csrf="))?.split("=")[1] || "";
    accountLogoutButton.disabled = true;
    try {
      await apiFetch("/api/auth/logout", { method: "POST", headers: csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {} });
      webSessionAuthenticated = false;
      currentProfile = null;
      if (webAuthScreen) webAuthScreen.hidden = false;
      if (sidebarProfile) sidebarProfile.textContent = "Sign in to view your profile";
      setStatus("Signed out");
    } catch (error) { setStatus(error.message || "Sign out failed."); }
    finally { accountLogoutButton.disabled = false; }
  });
  document.querySelectorAll("[data-auth-provider]").forEach((button) => {
    button.addEventListener("click", async () => {
      const provider = button.dataset.authProvider;
      button.disabled = true;
      try {
        const data = await apiFetch(`/api/auth/${provider}/start`);
        window.location.assign(data.authorization_url);
      } catch (error) {
        setStatus(error.message || "Sign-in is currently unavailable.");
        button.disabled = false;
      }
    });
  });
  $$(".nav-item")
    .forEach(
      (button) => {
        button.addEventListener(
          "click",
          async () => {
            const page =
              button.dataset.page;

            showPage(page);

            try {
              if (
                page === "profile"
              ) {
                await refreshProfile();
              }

              if (
                page === "history"
              ) {
                await loadHistory();
              }

              if (page === "leaderboard") {
                await loadLeaderboard();
              }

              if (
                page === "game" &&
                currentGame?.game_id
              ) {
                await loadGame(
                  currentGame.game_id,
                  true
                );
              }
            } catch (error) {
              setStatus(
                `Bishoply error: ${error.message}`
              );
            }
          }
        );
      }
    );

  $$("[data-page-shortcut]")
    .forEach(
      (button) => {
        button.addEventListener(
          "click",
          () => {
            showPage(
              button.dataset.pageShortcut
            );
          }
        );
      }
    );

  document.querySelectorAll("[data-practice-color]")
    .forEach(
      (button) => {
        button.addEventListener(
          "click",
          () => selectPracticeColor(button.dataset.practiceColor)
        );
      }
    );

  if (practiceNewOpponentButton) {
    practiceNewOpponentButton.addEventListener("click", () => {
      practiceReview.close();
      practiceGame = null;
      practiceAccessKey = null;
      practicePlayerColor = practiceChoice.player_color;
      practiceSelectedSquare = null;
      practiceLegalMoves = [];
      practiceCanMove = false;
      practiceBoardPieces = {};
      practiceReviewPosition = null;
      practiceReviewFlipped = false;
      clearPracticeHints();
      practiceMoveAnalysis = new Map();
      practiceAnnouncedPly = null;
      practiceSpokenKey = null;
      practiceAnalysisState = { status: "idle", message: "Analysis pending", classification: null };
      practicePendingAnalysis = null;
      if (practiceAnalysisTimer) {
        clearTimeout(practiceAnalysisTimer);
        practiceAnalysisTimer = null;
      }
      practiceCreateBusy = false;
      showPage("practice");
      setPracticeStatus("Choose a bot to start training.");
    });
  }

  if (practiceHintButton) {
    practiceHintButton.addEventListener("click", async (event) => {
      event.preventDefault();
      emmaVoice.unlock();
      try {
        const nextStage = Math.min(3, (practiceHintState?.stage || 0) + 1) || 1;
        await requestPracticeHint(nextStage);
        setPracticeStatus(`Hint ${nextStage} revealed.`);
      } catch (error) {
        setStatus(`Bishoply error: ${error.message}`);
      }
    });
  }

  practiceBestButton?.addEventListener("click", showPracticeBest);
  practiceWhyButton?.addEventListener("click", showPracticeWhy);
  practiceThreatButton?.addEventListener("click", showPracticeThreat);
  practiceSpeakButton?.addEventListener("click", speakPracticeCoach);

  if (practiceResignButton) {
    practiceResignButton.addEventListener("click", async () => {
      try {
        await resignPracticeGame();
      } catch (error) {
        setStatus(`Bishoply error: ${error.message}`);
      }
    });
  }

  if (practiceUndoButton) {
    practiceUndoButton.addEventListener("click", async () => {
      try {
        await undoPracticeGame();
      } catch (error) {
        setPracticeStatus(error.message || "Undo unavailable.");
        renderPracticeShell();
      }
    });
  }

  if (practiceRestartButton) {
    practiceRestartButton.addEventListener("click", async () => {
      try {
        await restartPracticeGame();
      } catch (error) {
        practiceCreateBusy = false;
        renderPracticeView("select");
        setStatus(`Bishoply error: ${error.message}`);
      }
    });
  }

  if (practiceEvalToggle) {
    practiceEvalToggle.addEventListener("click", () => {
      emmaVoice.unlock();
      practiceEvalVisible = !practiceEvalVisible;
      try {
        localStorage.setItem("bishoply.practice.evalbar", practiceEvalVisible ? "on" : "off");
      } catch {}
      renderPracticeEvalPreference();
    });
  }

  if (practiceSoundButton) practiceSoundButton.addEventListener("click", () => emmaVoice.unlock(), { capture: true });
  if (practiceEmmaVoiceButton) practiceEmmaVoiceButton.addEventListener("click", () => {
    emmaVoice.unlock();
    emmaVoice.setEnabled(!emmaVoice.enabled);
    practiceEmmaVoiceButton.textContent = `Emma Voice: ${emmaVoice.enabled ? "On" : "Off"}`;
    practiceEmmaVoiceButton.setAttribute("aria-pressed", String(emmaVoice.enabled));
    if (!emmaVoice.available() && !emmaVoice.remoteSpeak) practiceEmmaVoiceButton.textContent = "Emma Voice: Unavailable";
    if (emmaVoice.enabled) {
      const analysis = currentPracticeAnalysis();
      const coach = getIntelligenceResult(analysis)?.coach;
      if (coach?.message) {
        const key = `${practiceGame?.game_id || "practice"}:${latestPracticePlayerMove()?.ply || 0}:${coach.message}`;
        practiceSpokenKey = key;
        emmaVoice.speak(coach.message);
      }
    }
  });
  if (practiceEmmaVoiceButton) {
    practiceEmmaVoiceButton.textContent = (emmaVoice.available() || emmaVoice.remoteSpeak) ? `Emma Voice: ${emmaVoice.enabled ? "On" : "Off"}` : "Emma Voice: Unavailable";
    practiceEmmaVoiceButton.setAttribute("aria-pressed", String(emmaVoice.enabled));
  }

  if (createGameButton) {
    createGameButton.addEventListener(
      "click",
      async () => {
        try {
          await findDuel();
        } catch (error) {
          setStatus(
            `Bishoply error: ${error.message}`
          );
        }
      }
    );
  }

  if (joinGameButton) {
    joinGameButton.addEventListener(
      "click",
      async () => {
        try {
          await joinGame();
        } catch (error) {
          setStatus(
            `Bishoply error: ${error.message}`
          );
        }
      }
    );
  }

  if (cancelMatchmakingButton) {
    cancelMatchmakingButton.addEventListener("click", async () => {
      try { await cancelDuelSearch(); }
      catch (error) { setStatus(`Bishoply error: ${error.message}`); }
    });
  }

  if (refreshHistoryButton) {
    refreshHistoryButton.addEventListener(
      "click",
      async () => {
        try {
          await loadHistory();

          setStatus(
            "History refreshed."
          );
        } catch (error) {
          setStatus(
            `Bishoply error: ${error.message}`
          );
        }
      }
    );
  }

  if (leaderboardRatingTab) leaderboardRatingTab.addEventListener("click", async () => { leaderboardKind = "rating"; leaderboardRatingTab.className = "gold-button"; leaderboardSrTab.className = "dark-button"; await loadLeaderboard(); });
  if (leaderboardSrTab) leaderboardSrTab.addEventListener("click", async () => { leaderboardKind = "sr"; leaderboardSrTab.className = "gold-button"; leaderboardRatingTab.className = "dark-button"; await loadLeaderboard(); });

  if (joinGameInput) {
    joinGameInput.addEventListener(
      "keydown",
      async (event) => {
        if (
          event.key ===
          "Enter"
        ) {
          try {
            await joinGame();
          } catch (error) {
            setStatus(
              `Bishoply error: ${error.message}`
            );
          }
        }
      }
    );
  }

  if (moveButton) {
    moveButton.addEventListener(
      "click",
      () => {
        setStatus(
          "Use the chess board to move your pieces."
        );
      }
    );
  }
}


async function setupBishoply() {
  try {
    appReady = false;

    setControlsEnabled(false);

    setConnectionLabel(
      "Connection Check"
    );

    setStatus(
      "Checking backend..."
    );

    await checkBackend();

    if (!isDiscordActivity) {
      if (sdkCheck) setCheck(sdkCheck, "Browser mode");
      let session = null;
      try { session = await apiFetch("/api/auth/session"); } catch (error) {
        if (error?.status !== 401) throw error;
      }
      webSessionAuthenticated = Boolean(session?.authenticated);
      currentProfile = session?.profile || null;
      appReady = Boolean(currentProfile && currentProfile.username_selected !== false);
      setControlsEnabled(appReady);
      setConnectionLabel("Connected");
      setStatus(appReady ? "Bishoply is ready." : "Signed out");
      if (webAuthScreen) webAuthScreen.hidden = appReady;
      if (profileCheck) setCheck(profileCheck, appReady ? "Profile loaded" : "Signed out");
      if (appReady) {
        renderProfile(currentProfile);
        await loadAccountConnections();
        await loadProfileCosmetics();
      } else if (webSessionAuthenticated && currentProfile) {
        renderProfile(currentProfile);
        showUsernameOnboarding();
      }
      if (sidebarProfile && !appReady) sidebarProfile.textContent = "Sign in to view your profile";
      if (appSplash) {
        appSplash.classList.add("is-ready");
        window.setTimeout(() => appSplash.remove(), 180);
      }
      renderEmptyGame();
      renderPracticeShell();
      await loadPracticeBots();
      if (appReady) await recoverActivePractice();
      return;
    }

    setStatus(
      "Connecting to Discord..."
    );

    discordSdk = new DiscordSDK(CLIENT_ID);
    await discordSdk.ready();

    setCheck(
      sdkCheck,
      "SDK ready"
    );

    const { code } =
      await discordSdk.commands.authorize({
        client_id:
          CLIENT_ID,

        response_type:
          "code",

        state:
          "",

        prompt:
          "none",

        scope: [
          "identify",
        ],
      });

    const tokenData =
      await apiFetch(
        "/api/auth/discord",
        {
          method:
            "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body:
            JSON.stringify({
              code,
          }),
        }
      );

    discordAccessToken = tokenData.access_token;
    apiTransport.setToken(discordAccessToken);

    const auth =
      await discordSdk.commands.authenticate({
        access_token:
          tokenData.access_token,
      });

    if (
      !auth?.user?.id
    ) {
      throw new Error(
        "Discord authentication returned no user."
      );
    }

    currentProfile =
      await apiFetch(
        `/api/profile/${auth.user.id}`
      );

    appReady = true;

    renderProfile(
      currentProfile
    );
    await loadProfileCosmetics();

    setControlsEnabled(true);

    setCheck(
      profileCheck,
      "Profile loaded"
    );

    setConnectionLabel(
      "Connected"
    );

    if (appSplash) {
      appSplash.classList.add("is-ready");
      window.setTimeout(() => appSplash.remove(), 180);
    }

    setStatus(
      "Bishoply is ready."
    );

    renderEmptyGame();
    renderPracticeShell();
    await loadPracticeBots();
    await recoverActivePractice();

    // History is a secondary panel. A transient history failure must not
    // invalidate an otherwise authenticated, playable session.
    try {
      await loadHistory();
    } catch (error) {
      if (import.meta.env?.DEV) {
        console.debug("[Bishoply Startup] history load skipped", {
          status: error?.status || 0,
          kind: error?.kind || "request_error",
          message: error?.message || "",
        });
      }
      if (historyList) {
        historyList.innerHTML = `<div class="empty-mini"><strong>History temporarily unavailable.</strong><span>Try again shortly.</span></div>`;
      }
    }

    startGameSync();

  } catch (error) {
    console.error("Bishoply startup failed:", error?.name || "Error", error?.message || "Unknown error");

    appReady = false;

    setControlsEnabled(false);

    setConnectionLabel(
      "Connection Error"
    );

    setStatus(
      `Bishoply could not start: ${error?.message || "Please refresh and try again."}`
    );
    if (appSplash) {
      appSplash.classList.add("is-ready");
      window.setTimeout(() => appSplash.remove(), 180);
    }
  }
}


installStyles();

bindEvents();

renderEmptyGame();

setupBishoply();
