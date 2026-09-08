import { DiscordSDK } from "@discord/embedded-app-sdk";
export { DiscordSDK };
export function createDiscordClient(clientId) { return new DiscordSDK(clientId); }
