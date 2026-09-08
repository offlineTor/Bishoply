import { isDiscordRuntime } from "./runtime.js";

export class ApiTransport {
  constructor({ base = "", proxy = false, token = null } = {}) {
    this.base = base.replace(/\/$/, ""); this.proxy = proxy; this.token = token;
  }
  setToken(token) { this.token = token; }
  url(path) {
    const normalized = path.startsWith("/") ? path : `/${path}`;
    if (/^https?:\/\//i.test(path)) {
      if (this.proxy) throw new Error("Discord API transport rejects absolute backend URLs");
      return path;
    }
    if (!this.proxy) return `${this.base}${normalized}`;
    return normalized === "/health" || normalized === "/api/health" ? "/api/health" : `/api${normalized}`;
  }
  headers(headers = {}) { return this.token ? { ...headers, Authorization: `Bearer ${this.token}` } : headers; }
  credentials() { return this.proxy ? "omit" : "include"; }
}

export function createApiTransport() {
  return isDiscordRuntime
    ? new ApiTransport({ proxy: true, base: import.meta.env?.VITE_API_PROXY_BASE || "/api" })
    : new ApiTransport({ base: import.meta.env?.VITE_API_BASE_URL || "" });
}
