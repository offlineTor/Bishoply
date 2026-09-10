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
    user_id = await accounts.session_user(request)
    payload = await request.json()
    if not isinstance(payload, dict) or not payload.get("sku"):
        raise HTTPException(422, "A product sku is required")
    sku = payload["sku"]
    return await shop.create_checkout(user_id, sku, payload.get("success_url", "") or "", payload.get("cancel_url", "") or "")

@router.post("/webhook")
async def webhook(request: Request):
    event = shop.verify_webhook(await request.body(), request.headers.get("stripe-signature", ""))
    return await shop.fulfill_webhook(event)
