import { createWebRouter } from "./router.js";

/** Web entry boundary. It deliberately has no Discord SDK/auth imports. */
export function startWebApp({ onRoute, win = window } = {}) {
  const router = createWebRouter({ onRoute, win });
  router.start();
  return router;
}
