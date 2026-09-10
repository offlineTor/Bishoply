import { startLegacyApp } from "../shared/legacy-app.js";

/** Discord Activity product boundary. No Web router/session bootstrap. */
export function startDiscordApp() {
  return startLegacyApp({ product: "discord" });
}
