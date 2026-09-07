import { escape, isCompleted, resultSummary, formatTermination } from "./game-result.js";
import { CLASSIFICATION_UI, classificationUi, classificationBadge } from "./classification-ui.js";
import { LAUNCH_FEATURES } from "./launch-config.js";
const CATEGORIES = ["Best", "Excellent", "Good", "Book", "Inaccuracy", "Mistake", "Miss", "Blunder", "Forced"];
const ICONS = Object.fromEntries(Object.entries(CLASSIFICATION_UI).map(([key, value]) => [key, value.icon]));
const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const intelligenceOf = result => result?.intelligence || null;
const classificationOf = result => intelligenceOf(result) ? intelligenceOf(result).move_quality?.classification || null : result?.classification || null;
const evaluationOf = result => intelligenceOf(result) ? intelligenceOf(result).evaluation || null : result?.evaluation_after || null;
const accuracyOf = (result, color) => result?.[`${color}_bishoply_accuracy_v1`] ?? result?.[`${color}_accuracy`];
export class GameReview {
  constructor(element, fetchApi, showPosition, flip, backToResults, options = {}) {
    Object.assign(this, {element,fetchApi,showPosition,flip,backToResults});
    this.rootSelector = options.rootSelector || "#page-game";
    this.title = options.title || "Current Game";
    this.baseTitle = options.baseTitle || "Current Game";
    this.requestPath = options.requestPath || ((game) => `/api/games/${encodeURIComponent(game.game_id)}/analysis`);
    this.requestHeaders = options.requestHeaders || (() => ({}));
    this.staged = Boolean(options.staged);
    this.active = false;
    this.reviewing = !this.staged;
    this.index = -1;
    this.sequence = 0;
  }
  load(game) {
    if (this.game?.game_id !== game.game_id) {
      this.close(); this.result = null; this.data = null; this.changed = new Set(); this.intelligenceLogged = false;
    }
    this.game = game;
    if (!isCompleted(game)) this.close();
    if (this.active) this.render();
  }
  open() {
    if (!LAUNCH_FEATURES.gameReview) return;
    if (!isCompleted(this.game)) return;
    this.active = true;
    this.reviewing = false;
    this.reviewing = false;
    this.element.hidden = false;
    this.root = document.querySelector(this.rootSelector);
    this.root?.classList.add("review-open");
    this.root?.classList.toggle("review-detail-open", this.reviewing);
    const title = this.root?.querySelector(".game-header h2");
    if (title) title.textContent = this.title;
    this.index = -1;
    this.showPosition(null);
    this.root?.scrollIntoView({block:"start"});
    this.request(false);
  }
  close() {
    this.active = false; this.sequence++;
    clearTimeout(this.timer);
    this.element.hidden = true;
    this.root = document.querySelector(this.rootSelector);
    this.root?.classList.remove("review-open");
    this.root?.classList.remove("review-detail-open");
    const title = this.root?.querySelector(".game-header h2");
    if (title) title.textContent = this.baseTitle;
    this.showPosition(null);
  }
  startReview() {
    if (!this.active) return;
    this.reviewing = true;
    this.root?.classList.add("review-detail-open");
    this.index = this.game.moves.length - 1;
    this.select(this.index);
  }
  async request(start) {
    if (!this.active || !isCompleted(this.game)) return;
    const sequence = ++this.sequence;
    const id = this.game.game_id;
    clearTimeout(this.timer);
    try {
      const path = this.requestPath(this.game, start);
      const headers = this.requestHeaders(this.game) || {};
      const data = await this.fetchApi(path, {method:start ? "POST" : "GET", headers});
      if (!this.active || sequence !== this.sequence || this.game.game_id !== id) return;
      this.error = null;
      const previous = new Map((this.result?.moves || []).map(m => [m.ply,classificationOf(m)]));
      this.changed = new Set((data.result?.moves || []).filter(m => previous.has(m.ply) && previous.get(m.ply) !== classificationOf(m)).map(m => m.ply));
      if (data.result) this.result = data.result;
      this.data = data;
      if (!this.intelligenceLogged && data.result?.moves?.some(move => intelligenceOf(move))) {
        this.intelligenceLogged = true;
        console.debug("[Bishoply] Intelligence V1 active");
      }
      this.render(); // Deliberately never calls select: incoming analysis cannot move the board.
      if (data.status === "not_started") { this.request(true); return; }
      if (["queued","analyzing","fast_analysis","deep_analysis"].includes(data.status) || ["queued","analyzing"].includes(data.pending_status)) {
        this.timer = setTimeout(() => this.request(false), document.hidden ? 5000 : 2000);
      }
    } catch (error) {
      if (!this.active || sequence !== this.sequence) return;
      this.error = error.message;
      this.render(); // Stored game remains navigable even if Stockfish/network fails.
    }
  }
  select(index, before = false) {
    this.index = Math.max(-1, Math.min(this.game.moves.length-1,index));
    const move = this.game.moves[this.index];
    const fen = before ? (this.index > 0 ? this.game.moves[this.index-1].fen_after : this.game.starting_fen || START)
      : move?.fen_after || this.game.starting_fen || START;
    this.showPosition({fen, moves:move && !before ? [{uci:move.uci}] : [],turn:fen.split(" ")[1] === "w" ? "white" : "black"});
    this.render();
  }
  render() {
    if (!this.active || !isCompleted(this.game)) return;
    const expanded = [...this.element.querySelectorAll("details[open][data-review-detail]")].map(d => d.dataset.reviewDetail);
    const scroll = this.element.querySelector(".review-moves")?.scrollTop || 0;
    const focused = this.element.contains(document.activeElement) ? document.activeElement?.getAttribute("data-focus") : null;
    const result = this.result;
    const analyzed = new Map((result?.moves || []).map(m => [m.ply,m]));
    const selected = analyzed.get(this.index+1);
    const selectedIntelligence = intelligenceOf(selected);
    const selectedClassification = classificationOf(selected);
    const move = this.game.moves[this.index];
    const total = this.game.moves.length;
    const status = this.data?.status || "queued";
    const stage = result?.stage === "deep_queued" ? "Refining analysis…" : status === "deep_analysis" ? "Refining analysis…" : status === "complete" ? "" : status === "failed" ? "Analysis incomplete" : "Review ready · refining";
    const done = this.data?.analyzed_plies ?? this.data?.progress ?? 0;
    const counts = color => CATEGORIES.map(c => `<span class="review-count"><b>${ICONS[c]} ${c}</b><em>${(result?.moves || []).filter(m => m.color === color && classificationOf(m) === c).length}</em></span>`).join("");
    const whiteOutcome = a => { const e = evaluationOf(a); if (e?.win_probability != null) return e.perspective === "black" ? 1 - e.win_probability : e.win_probability; return a?.white_outcome; };
    const points = this.game.moves.map((m,i) => { const a=analyzed.get(i+1), outcome=whiteOutcome(a); return outcome != null ? `<circle cx="${total <= 1 ? 300 : i/(total-1)*600}" cy="${100-outcome*100}" r="2" fill="#cfb77c"/>` : ""; }).join("");
    const segments = this.game.moves.slice(1).map((_,i) => {const a=analyzed.get(i+1),b=analyzed.get(i+2),ao=whiteOutcome(a),bo=whiteOutcome(b);return ao != null && bo != null ? `<path d="M${i/(total-1)*600} ${100-ao*100}L${(i+1)/(total-1)*600} ${100-bo*100}" stroke="#cfb77c" fill="none"/>` : "";}).join("");
    const evaluation = evaluationOf(selected);
    const sign = evaluation?.perspective === "black" ? -1 : 1;
    const evalText = evaluation?.mate != null ? `${evaluation.mate * sign < 0 ? "−" : ""}M${Math.abs(evaluation.mate)}`
      : evaluation?.cp != null ? `${evaluation.cp * sign >= 0 ? "+" : "−"}${Math.abs(evaluation.cp * sign / 100).toFixed(2)}` : "Evaluation pending";
    const summary = resultSummary(this.game);
    const practiceMeta = this.game?.hint_count != null || this.game?.assisted != null || this.game?.bot?.display_name || this.game?.bot_accuracy != null || this.game?.opening_name
      ? `<div class="review-notes">${this.game?.bot?.display_name ? `<span>Bot: ${escape(this.game.bot.display_name)}</span>` : ""}${this.game?.bot_accuracy != null ? `<span>Bot accuracy: ${Number(this.game.bot_accuracy).toFixed(1)}%</span>` : ""}${this.game?.opening_name ? `<span>Opening: ${escape(this.game.opening_name)}</span>` : ""}${this.game?.hint_count != null ? `<span>Hints Used: ${this.game.hint_count}</span>` : ""}${this.game?.assisted != null ? `<span>Assisted: ${this.game.assisted ? "Yes" : "No"}</span>` : ""}</div>`
      : "";
    const player = color => this.game[color]?.display_name || (color === "white" ? "White" : "Black");
    const count = (color, category) => (result?.moves || []).filter(m => m.color === color && classificationOf(m) === category).length;
    const summaryRows = CATEGORIES.filter(category => category !== "Forced").map(category => `<div class="review-summary-row"><span>${ICONS[category]} ${category}</span><b>${count("white", category)}</b><b>${count("black", category)}</b></div>`).join("");
    const coachCopy = {Best:"Strong choice. This keeps your advantage.",Excellent:"Very accurate. You preserved the position.",Good:"Solid move. There was a slightly stronger continuation.",Book:"This follows known opening theory.",Inaccuracy:"This gives up some of your advantage.",Mistake:"This changes the position significantly.",Miss:"There was a stronger tactical opportunity here.",Blunder:"This allows a major tactical swing.",Forced:"There was only one viable move."};
    const coachText = selectedIntelligence
      ? (selectedIntelligence.coach?.should_comment && selectedIntelligence.coach.message ? selectedIntelligence.coach.message : "")
      : (selectedClassification ? coachCopy[selectedClassification] || "Bishoply has analyzed this move." : "Select a move to see Bishoply's explanation.");
    const emmaSummary = result?.emma_summary || this.data?.emma_summary || this.game?.emma_summary;
    const emmaSummaryMarkup = emmaSummary?.message
      ? `<section class="review-card review-emma-summary"><strong>EMMA</strong><p>${escape(emmaSummary.message)}</p></section>` : "";
    const summaryMarkup = `<section class="review-summary-screen"><div class="review-summary-hero"><span class="eyebrow gold">Bishoply Game Review</span><h3>${escape(summary.title)}</h3><p>${escape(formatTermination(this.game.termination_reason))}</p></div><div class="review-player-summary"><article><span class="review-player-side">White</span><strong>${escape(player("white"))}</strong><b>${accuracyOf(result,"white") == null ? "—" : Number(accuracyOf(result,"white")).toFixed(1)+"%"}</b><small>Bishoply Accuracy</small></article><article><span class="review-player-side">Black</span><strong>${escape(player("black"))}</strong><b>${accuracyOf(result,"black") == null ? "—" : Number(accuracyOf(result,"black")).toFixed(1)+"%"}</b><small>Bishoply Accuracy</small></article></div>${emmaSummaryMarkup}<div class="review-summary-card"><div class="review-summary-columns"><strong>White</strong><strong>Black</strong></div>${summaryRows}</div>${practiceMeta}<div class="review-summary-progress"><span>${stage}</span><span>${done} / ${total} plies</span><progress max="${Math.max(1,total)}" value="${done}"></progress></div><button class="gold-button review-start-button" data-start-review>Start Review</button><button data-focus="back" class="dark-button" data-back-results>Back to Results</button></section>`;
    const reviewMarkup = `<div class="review-heading"><span class="eyebrow gold">Bishoply Game Review</span><h3>${escape(summary.title)} · ${escape(this.game.result)}</h3><p>${escape(formatTermination(this.game.termination_reason))}</p><button data-focus="back" class="dark-button" data-back-results>Back to Results</button></div>
      <div class="review-accuracy">${["white","black"].map(color => `<div><span>${escape(this.game[color]?.display_name || color)} · ${color}</span><strong>${accuracyOf(result,color) == null ? "—" : Number(accuracyOf(result,color)).toFixed(1)+"%"}</strong><small>Bishoply Accuracy</small><details data-review-detail="counts-${color}"><summary>Move counts</summary>${counts(color)}</details></div>`).join("")}</div>
      <div class="review-progress" role="status"><span>${stage}</span><span>${done} / ${total} plies</span><progress max="${Math.max(1,total)}" value="${done}"></progress><small>${status === "deep_analysis" ? "Labels are being refined." : status === "complete" ? "Authoritative review · Accuracy is experimental" : "Review is ready while analysis continues."}</small></div>
      ${this.error || status === "failed" ? `<p role="alert">${escape(this.error || this.data.error || "Some moves need another attempt.")}</p><button class="dark-button" data-retry>Retry analysis</button>` : ""}
      <section class="review-card review-navigation-card"><div class="review-controls"><button data-focus="begin" class="dark-button" data-begin aria-label="Beginning">|←</button><button data-focus="prev" class="dark-button" data-review-prev ${this.index < 0 ? "disabled" : ""} aria-label="Previous move">←</button><button data-focus="next" class="dark-button" data-review-next ${this.index >= total-1 ? "disabled" : ""} aria-label="Next move">→</button><button data-focus="end" class="dark-button" data-end aria-label="End">→|</button><button data-focus="flip" class="dark-button" data-flip>Flip</button></div></section>
      <section class="review-card review-eval-card"><span>GAME EVAL</span><svg viewBox="0 0 600 100" role="img" aria-label="Game evaluation graph"><path d="M0 50H600" stroke="#555" stroke-dasharray="4 4"/>${segments}${points}</svg></section>
      <section class="review-card review-current-card">${coachText ? `<div class="review-coach"><span class="review-coach-mark">♝</span><div><strong>EMMA</strong><p>${escape(coachText)}</p></div></div>` : ""}<div class="review-selection"><strong>${move ? `${move.move_number}${move.color === "white" ? "." : "…"} ${escape(move.san)}` : "Starting position"}</strong>${selectedClassification ? classificationBadge(selectedClassification) : ""}<p>${move ? escape(evalText) : ""}</p></div></section>
      ${selectedIntelligence?.best_move || selected?.pv ? `<details class="review-card review-best-line" data-review-detail="pv"><summary>BEST LINE <span aria-hidden="true">▾</span></summary><p>${escape(selectedIntelligence?.best_move || (selected?.pv || []).join(" "))}</p><button class="dark-button" data-before>Show position before move</button><small>Same-position engine comparison.</small></details>` : ""}
      <section class="review-card review-history-card"><h4>MOVES</h4><div class="review-moves">${this.game.moves.map((m,i) => { const a=analyzed.get(i+1), label=classificationOf(a), ui=classificationUi(label);return `<button data-focus="ply-${i}" type="button" data-review-ply="${i}" class="review-move ${i === this.index ? "selected" : ""} ${this.changed?.has(i+1) ? "label-updated" : ""}" aria-label="${m.move_number} ${m.color} ${escape(m.san)} ${escape(label || "Pending")}"><span>${m.move_number}${m.color === "white" ? "." : "…"} ${escape(m.san)}</span><b class="review-move-icon ${ui?.className || "pending"}" title="${escape(label || "Pending")}">${ui?.icon || "…"}</b></button>`;}).join("")}</div></section>
      <details class="review-card review-technical" data-review-detail="technical"><summary>Analysis details <span aria-hidden="true">▾</span></summary><pre>${escape(JSON.stringify({engine:result?.engine,settings:result?.settings,revision:this.data?.analysis_revision,elapsed_seconds:result?.elapsed_seconds},null,2))}</pre><p>Common-root comparison. Great and Brilliant are disabled. Bishoply Accuracy remains experimental.</p></details>`;
    this.element.innerHTML = this.reviewing ? reviewMarkup : summaryMarkup;
    this.element.querySelectorAll("[data-review-ply]").forEach(b => b.onclick = () => this.select(Number(b.dataset.reviewPly)));
    const on = (selector, callback) => { const b=this.element.querySelector(selector); if (b) b.onclick=callback; };
    on("[data-review-prev]",()=>this.select(this.index-1)); on("[data-review-next]",()=>this.select(this.index+1));
    on("[data-begin]",()=>this.select(-1)); on("[data-end]",()=>this.select(total-1));
    on("[data-before]",()=>this.select(this.index,true)); on("[data-flip]",()=>this.flip());
    on("[data-back-results]",()=>{this.close();this.backToResults();}); on("[data-retry]",()=>this.request(true));
    on("[data-start-review]",()=>this.startReview());
    const movePanel = this.element.querySelector(".review-moves");
    if (movePanel) movePanel.scrollTop=scroll;
    expanded.forEach(key => { const detail=this.element.querySelector(`[data-review-detail="${key}"]`); if (detail) detail.open=true; });
    if (focused) this.element.querySelector(`[data-focus="${focused}"]`)?.focus({preventScroll:true});
  }
}
