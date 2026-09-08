"""Discord bot lifecycle shared by Render web process and local launcher."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress

import discord
from dotenv import load_dotenv

load_dotenv()
# Uvicorn configures this logger in Render; lifecycle messages are therefore
# captured alongside application startup logs.
log = logging.getLogger("uvicorn.error")
client: discord.Client | None = None
_task: asyncio.Task | None = None


def _token() -> str | None:
    return os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")


def _build_client() -> discord.Client:
    instance = discord.Client(intents=discord.Intents.default())

    @instance.event
    async def on_ready():
        log.info("Bishoply Discord bot ready: %s (%s guilds)", instance.user, len(instance.guilds))

    return instance


async def start_bot() -> asyncio.Task | None:
    """Start exactly one non-blocking Gateway task for this process."""
    global client, _task
    if _task and not _task.done():
        return _task
    token = _token()
    if not token:
        log.error("DISCORD_BOT_TOKEN is missing; bot integration is disabled")
        return None
    log.info("Starting Bishoply Discord Gateway")
    if client is None or client.is_closed():
        client = _build_client()

    async def run():
        try:
            await client.start(token)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.error("Discord Gateway connection failed (%s): gateway connection failed; API will continue running", type(error).__name__)

    _task = asyncio.create_task(run(), name="bishoply-discord-gateway")
    log.info("Discord Gateway task created")

    def report_unexpected_failure(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            log.error("Discord Gateway task stopped: %s", type(error).__name__)

    _task.add_done_callback(report_unexpected_failure)
    return _task


async def stop_bot() -> None:
    global _task
    if client is not None and not client.is_closed():
        with suppress(Exception):
            await client.close()
    if _task and not _task.done():
        _task.cancel()
        with suppress(asyncio.CancelledError):
            await _task
    _task = None


def run_standalone() -> None:
    token = _token()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is missing")
    _build_client().run(token)


if __name__ == "__main__":
    run_standalone()
