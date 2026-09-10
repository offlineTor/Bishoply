import { createWebRouter } from "./router.js";
import * as lab from "./lab.js";
import { startLegacyApp } from "../shared/legacy-app.js";

/** Standalone Web product boundary. No Discord SDK/proxy bootstrap. */
export function startWebApp({ win = window } = {}) {
  const router = createWebRouter({
    win,
    onRoute: ({ page }) => window.dispatchEvent(new CustomEvent("bishoply:web-route", { detail: { page } })),
  });
  startLegacyApp({ product: "web", lab });
  router.start();
  return router;
}
