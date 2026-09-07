"""Verify ownership at Practice creation using the existing Discord OAuth token."""
import httpx
from fastapi import Header, HTTPException


async def discord_identity(authorization: str = Header(...)):
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 4096:
        raise HTTPException(401,'Discord Bearer token required')
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response=await client.get('https://discord.com/api/users/@me',headers={'Authorization':f'Bearer {token}'})
    except httpx.HTTPError as exc:
        raise HTTPException(503,'Discord identity verification unavailable') from exc
    if response.status_code != 200:
        raise HTTPException(401,'Discord token is invalid or expired')
    try:
        return int(response.json()['id'])
    except (ValueError,KeyError,TypeError) as exc:
        raise HTTPException(503,'Discord identity response was invalid') from exc
