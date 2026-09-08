export const runtime = (import.meta.env?.VITE_RUNTIME || "").toLowerCase() ||
  (["frame_id", "instance_id", "platform"].every((key) => new URLSearchParams(window.location.search).get(key)) ? "discord" : "web");

export const isDiscordRuntime = runtime === "discord";
