/** Lightweight Web-only History API router. Discord never imports this module. */
export const WEB_ROUTES = Object.freeze(["/", "/play", "/bots", "/lab", "/history", "/leaderboard", "/shop", "/profile"]);

export function normalizeRoute(path = "/") {
  const clean = String(path).split("?")[0].replace(/\/+$/, "") || "/";
  if (clean.startsWith("/training/")) return { page: "training", gameId: clean.slice(10) };
  return { page: WEB_ROUTES.includes(clean) ? clean.slice(1) || "home" : "home" };
}

export function createWebRouter({ onRoute, win = window } = {}) {
  const navigate = (path, replace = false) => {
    const url = path.startsWith("/") ? path : `/${path}`;
    (replace ? win.history.replaceState : win.history.pushState).call(win.history, {}, "", url);
    onRoute?.(normalizeRoute(url));
  };
  const onPop = () => onRoute?.(normalizeRoute(win.location.pathname));
  win.addEventListener?.("popstate", onPop);
  return { navigate, start: onPop, dispose: () => win.removeEventListener?.("popstate", onPop) };
}
