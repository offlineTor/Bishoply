import { defineConfig } from "vite";

export default defineConfig(({ mode }) => {
  const apiBase = process.env.VITE_API_BASE_URL || "";
  const runtime = (process.env.VITE_RUNTIME || "").toLowerCase();
  if (!runtime || !["web", "discord"].includes(runtime)) throw new Error("VITE_RUNTIME must be explicitly set to web or discord");
  if (mode === "discord" || runtime === "discord") {
    if (!process.env.VITE_API_PROXY_BASE || !process.env.VITE_API_PROXY_BASE.startsWith("/")) throw new Error("Discord builds require a relative VITE_API_PROXY_BASE");
  } else {
    if (!/^https:\/\//i.test(apiBase)) throw new Error("Web builds require an HTTPS VITE_API_BASE_URL");
  }
  return {
  define: { __BISHOPLY_API_BASE__: JSON.stringify(apiBase) },
  build: {
    sourcemap: false,
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: [
      ".trycloudflare.com",
      ".discordsays.com"
    ],
    proxy: {
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      },
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
  };
});
