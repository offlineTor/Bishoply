import { resultSummary } from "./game-result.js";
// Original synthesized piece sounds; replace voices with licensed/local assets later.
export class ChessSound {
  constructor(button) {
    this.buttons = Array.isArray(button) ? button.filter(Boolean) : [button].filter(Boolean);
    try { this.enabled = localStorage.getItem("bishoply.chess.sound") !== "off"; }
    catch { this.enabled = true; }
    this.context = null;
    const unlock = () => {
      if (!this.enabled) return;
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      this.context ||= new AudioContext();
      this.context.resume().catch(() => {});
    };
    document.addEventListener("pointerdown", unlock, { passive: true });
    document.addEventListener("keydown", unlock);
    this.buttons.forEach(button => button.addEventListener("click", () => {
      this.enabled = !this.enabled;
      try { localStorage.setItem("bishoply.chess.sound", this.enabled ? "on" : "off"); } catch {}
      if (this.enabled) unlock();
      this.update();
    }));
    this.update();
  }
  update() {
    this.buttons.forEach(button => {
      if (!button) return;
      button.textContent = this.enabled ? "Sound on" : "Sound off";
      button.setAttribute("aria-pressed", String(this.enabled));
      button.setAttribute("aria-label", this.enabled ? "Mute chess sounds" : "Enable chess sounds");
    });
  }
  play(kind) {
    if (!this.enabled || this.context?.state !== "running" || document.hidden) return;
    const voices = { move: [260], capture: [180, 360], check: [480, 640],
      castle: [230, 300], start: [330, 440], end: [360, 240, 180], victory: [330, 440, 550], defeat: [220, 165], draw: [300, 300],
      positive: [390, 520], mistake: [240, 190], blunder: [180, 140] };
    (voices[kind] || voices.move).forEach((frequency, index) => {
      const at = this.context.currentTime + index * 0.065;
      const oscillator = this.context.createOscillator();
      const gain = this.context.createGain();
      const filter = this.context.createBiquadFilter();
      oscillator.type = "triangle";
      oscillator.frequency.setValueAtTime(frequency, at);
      oscillator.frequency.exponentialRampToValueAtTime(frequency * 0.55, at + 0.08);
      filter.type = "lowpass";
      filter.frequency.value = 1100;
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(0.07, at + 0.003);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.11);
      oscillator.connect(filter).connect(gain).connect(this.context.destination);
      oscillator.start(at);
      oscillator.stop(at + 0.12);
      oscillator.onended = () => { oscillator.disconnect(); filter.disconnect(); gain.disconnect(); };
    });
  }
  transition(previous, game, color) {
    // Initial loads, refreshes, and history navigation never replay old sounds.
    if (!previous || previous.game_id !== game.game_id) return;
    if (previous.status === "waiting" && game.status === "active") return this.play("start");
    if (["white_win", "black_win", "draw"].includes(game.status) && previous.status !== game.status) return this.play(resultSummary(game, color).outcome);
    if ((game.moves?.length || 0) <= (previous.moves?.length || 0)) return;
    const san = game.moves.at(-1)?.san || "";
    this.play(/[+#]/.test(san) ? "check" : san.startsWith("O-O") ? "castle" : san.includes("x") ? "capture" : "move");
  }
}
