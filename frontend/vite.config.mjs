import { defineConfig } from "vite";

export default defineConfig(({ mode }) => {
  const apiBase = process.env.VITE_API_BASE_URL || "";
  const runtime = (process.env.VITE_RUNTIME || (mode === "discord" ? "discord" : "web")).toLowerCase();
  if (mode === "discord" || runtime === "discord") {
    if (runtime !== "discord") throw new Error("Discord builds require VITE_RUNTIME=discord");
    if (process.env.VITE_API_PROXY_BASE && !process.env.VITE_API_PROXY_BASE.startsWith("/")) throw new Error("VITE_API_PROXY_BASE must be a relative proxy path");
  } else if (mode === "production" && process.env.BISHOPLY_ENV === "production" && !/^https:\/\//i.test(apiBase)) {
    throw new Error("VITE_API_BASE_URL must be an HTTPS URL for production builds");
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
