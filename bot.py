import os

import discord
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")


intents = discord.Intents.default()

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print("")
    print("========================================")
    print("Bishoply bot is online.")
    print(f"Logged in as: {client.user}")
    print(f"Discord ID: {client.user.id}")
    print(f"Connected servers: {len(client.guilds)}")
    print("========================================")
    print("")


client.run(TOKEN)
