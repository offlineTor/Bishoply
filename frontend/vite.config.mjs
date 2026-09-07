import { defineConfig } from "vite";

export default defineConfig(({ mode }) => {
  const apiBase = process.env.VITE_API_BASE_URL || "";
  if (mode === "production" && process.env.BISHOPLY_ENV === "production" && !/^https:\/\//i.test(apiBase)) {
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
