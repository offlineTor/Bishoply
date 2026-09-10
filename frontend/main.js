import { isDiscordRuntime } from "./shared/runtime.js";

// The entrypoint selects exactly one product. Product startup and DOM ownership
// live behind the selected bootstrap boundary.
const bootstrap = isDiscordRuntime
  ? import("./discord/bootstrap.js")
  : import("./web/bootstrap.js");

bootstrap.then(({ startDiscordApp, startWebApp }) => {
  if (isDiscordRuntime) return startDiscordApp?.();
  return startWebApp?.();
}).catch((error) => {
  console.error("Bishoply startup failed", error);
});
