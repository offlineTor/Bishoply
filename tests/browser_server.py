"""Isolated API for browser regression checks; never opens bishoply.db."""
import tempfile
from pathlib import Path
from fastapi import FastAPI
from backend.database import db as database
from backend.api.games import router as games_router
from backend.api.analysis import router as analysis_router
from backend.api.profile import router as profile_router
from backend.analysis import service

_temp = tempfile.TemporaryDirectory(prefix="bishoply-browser-")
database.DB_PATH = Path(_temp.name) / "browser.db"
app = FastAPI()
app.include_router(games_router)
app.include_router(analysis_router)
app.include_router(profile_router)


@app.on_event("startup")
async def startup():
    await database.initialize_database()
    await database.get_or_create_user(101, "white", "Alex Morgan")
    await database.get_or_create_user(202, "black", "Jordan Lee")
    await service.initialize()
