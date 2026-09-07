import os
import tempfile

import os
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel
from backend.practice.auth import discord_identity

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak")
async def speak(payload: SpeakRequest, authorization: str | None = Header(default=None)):
    if os.getenv("BISHOPLY_ENV", "development").lower() == "production":
        if not authorization:
            raise HTTPException(status_code=401, detail="Discord authentication required")
        await discord_identity(authorization)
    text = payload.text.strip()[:1800]
    if not text:
        raise HTTPException(status_code=400, detail="Voice text is empty")
    try:
        import edge_tts
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Emma voice service is unavailable") from exc

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp:
            path = temp.name
        voice = os.getenv("BISHOPLY_EMMA_VOICE", "en-US-EmmaMultilingualNeural")
        await edge_tts.Communicate(text, voice).save(path)
        with open(path, "rb") as stream:
            return Response(stream.read(), media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Emma voice generation failed") from exc
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
