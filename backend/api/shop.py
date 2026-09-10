from fastapi import APIRouter, HTTPException, Request
from backend import accounts
from backend.services import shop

router = APIRouter(prefix="/api/shop", tags=["shop"])

@router.get("")
async def read_shop(request: Request):
    user_id = None
    try:
        user_id = await accounts.session_user(request)
    except HTTPException:
        # Public catalog browsing is available while signed out. Unexpected
        # database/runtime errors must still surface to the caller.
        pass
    return await shop.catalog(user_id)

@router.post("/checkout")
async def checkout(request: Request):
    await accounts.session_user(request)
    return await shop.checkout_status()
