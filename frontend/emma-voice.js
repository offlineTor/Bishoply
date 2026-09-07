// Browser-backed Emma voice abstraction. No voice name is assumed to exist.
export class EmmaVoiceManager {
  constructor(options = {}) {
    this.enabled = this.readPreference();
    this.volume = 0.9;
    this.rate = 0.95;
    this.pitch = 1;
    this.unlocked = false;
    this.voices = [];
    this.onEvent = null;
    this.remoteSpeak = options.remoteSpeak || null;
    this.currentAudio = null;
    if (this.available()) {
      const refresh = () => { this.voices = window.speechSynthesis.getVoices?.() || []; this.onEvent?.({ action: "voiceschanged", voices_count: this.voices.length }); };
      window.speechSynthesis.addEventListener?.("voiceschanged", refresh);
      refresh();
    }
  }

  readPreference() {
    try { return localStorage.getItem("bishoply.emma.voice") === "on"; }
    catch { return false; }
  }

  setEnabled(enabled) {
    this.enabled = Boolean(enabled);
    if (!this.enabled) this.stop();
    try { localStorage.setItem("bishoply.emma.voice", this.enabled ? "on" : "off"); } catch {}
  }

  available() { return typeof window !== "undefined" && "speechSynthesis" in window; }

  unlock() {
    if (!this.available() && !this.remoteSpeak) return false;
    if (!this.available()) { this.unlocked = true; return true; }
    this.voices = window.speechSynthesis.getVoices?.() || this.voices;
    this.unlocked = true;
    try { window.speechSynthesis.resume(); } catch {}
    return true;
  }

  preferredVoice() {
    if (!this.available()) return null;
    const voices = this.voices.length ? this.voices : (window.speechSynthesis.getVoices?.() || []);
    return voices.find(voice => /en/i.test(voice.lang) && /female|samantha|victoria|karen|zira|ava/i.test(voice.name))
      || voices.find(voice => /en/i.test(voice.lang)) || voices[0] || null;
  }

  async speak(text) {
    if (!this.enabled || !text || (!this.available() && !this.remoteSpeak)) return false;
    this.unlock();
    if (this.remoteSpeak) {
      this.stop();
      this.onEvent?.({ action: "queued", voice: "Bishoply Emma TTS", message: text });
      try {
        const audio = await this.remoteSpeak(text);
        if (!this.enabled) return false;
        this.currentAudio = audio;
        this.onEvent?.({ action: "started", voice: "Bishoply Emma TTS", message: text });
        await audio.play();
        audio.addEventListener("ended", () => { this.currentAudio = null; this.onEvent?.({ action: "completed", voice: "Bishoply Emma TTS", message: text }); }, { once: true });
        return true;
      } catch (error) {
        this.currentAudio = null;
        this.onEvent?.({ action: "failed", error: error?.message || "audio playback failed", voice: "Bishoply Emma TTS", message: text });
        return false;
      }
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.volume = this.volume;
    utterance.rate = this.rate;
    utterance.pitch = this.pitch;
    const voice = this.preferredVoice();
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang || "en-US";
    utterance.onstart = () => this.onEvent?.({ action: "started", voice: voice?.name || "default", message: text });
    utterance.onend = () => this.onEvent?.({ action: "completed", voice: voice?.name || "default", message: text });
    utterance.onerror = event => this.onEvent?.({ action: "failed", error: event.error || "speech synthesis error", voice: voice?.name || "default", message: text });
    this.onEvent?.({ action: "queued", voice: voice?.name || "default", message: text });
    window.speechSynthesis.speak(utterance);
    return true;
  }

  stop() {
    if (this.currentAudio) { this.currentAudio.pause(); this.currentAudio.currentTime = 0; this.currentAudio = null; }
    if (this.available()) window.speechSynthesis.cancel();
  }
}
