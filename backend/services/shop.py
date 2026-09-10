"""Server-authoritative Bishoply cosmetic catalog and Crown configuration."""
import hashlib, hmac, json, os, time
import httpx
from fastapi import HTTPException
from backend.database import db

RARITIES = ("Classic", "Refined", "Elite", "Mythic", "Eclipse")
CATALOG = (
    ("board-obsidian-court", "Obsidian Court", "board_skin", "Classic", "A dark tournament board with warm ivory squares.", 0),
    ("board-midnight-gold", "Midnight Gold", "board_skin", "Refined", "Charcoal and gold for long evening sessions.", 499),
    ("board-marble-dynasty", "Marble Dynasty", "board_skin", "Elite", "A polished marble board inspired by grand halls.", 799),
    ("board-celestial-grid", "Celestial Grid", "board_skin", "Mythic", "A restrained constellation pattern for the board edge.", 999),
    ("pieces-royal-ivory", "Royal Ivory", "piece_set", "Classic", "Readable ivory pieces with a carved silhouette.", 0),
    ("pieces-glass-cathedral", "Glass Cathedral", "piece_set", "Mythic", "Original translucent pieces with strong contrast.", 999),
    ("frame-crown", "Crown", "profile_frame", "Elite", "A precise gold profile frame.", 599),
    ("frame-eclipse", "Eclipse", "profile_frame", "Eclipse", "The signature Bishoply frame.", 1499),
    ("effect-golden-capture", "Golden Capture", "capture_sound", "Refined", "A concise golden capture accent.", 299),
    ("effect-eclipse-check", "Eclipse Check", "check_sound", "Elite", "A measured warning tone for check.", 399),
    ("sound-classic-hall", "Classic Hall", "sound_pack", "Classic", "A quiet classical match sound set.", 0),
    ("sound-grandmaster-suite", "Grandmaster Suite", "sound_pack", "Mythic", "A complete premium sound suite.", 899),
)
BUNDLES = (
    {"sku":"opening-collection", "name":"Opening Collection", "price_cents":799, "items":["board-obsidian-court","pieces-royal-ivory","sound-classic-hall"]},
    {"sku":"royal-collection", "name":"Royal Collection", "price_cents":1699, "items":["board-midnight-gold","frame-crown","effect-golden-capture"]},
    {"sku":"eclipse-collection", "name":"Eclipse Collection", "price_cents":2999, "items":["board-celestial-grid","frame-eclipse","effect-eclipse-check","sound-grandmaster-suite"]},
    {"sku":"founder-collection", "name":"Founder Collection", "price_cents":3999, "items":["board-marble-dynasty","pieces-glass-cathedral","frame-eclipse","sound-grandmaster-suite"]},
)
CROWN_PLANS = (
    {"sku":"crown-monthly", "name":"Bishoply Crown Monthly", "price_cents":799, "interval":"month"},
    {"sku":"crown-annual", "name":"Bishoply Crown Annual", "price_cents":6999, "interval":"year"},
)

async def initialize():
    connection = await db.connect()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        for sku, name, category, rarity, description, price in CATALOG:
            await connection.execute("INSERT OR IGNORE INTO cosmetics(sku,name,category,rarity,metadata_json,active,price_cents) VALUES (?,?,?,?,?,1,?)", (sku,name,category,rarity,description,price))
        await connection.commit()
    except Exception:
        await connection.rollback(); raise
    finally: await connection.close()

async def catalog(user_id=None):
    connection = await db.connect()
    try:
        rows = await (await connection.execute("SELECT c.id,c.sku,c.name,c.category,c.rarity,c.metadata_json,c.price_cents,c.active,CASE WHEN u.user_id IS NULL THEN 0 ELSE 1 END AS owned FROM cosmetics c LEFT JOIN user_cosmetics u ON u.cosmetic_id=c.id AND u.user_id=? WHERE c.active=1 ORDER BY c.category,c.price_cents,c.id", (user_id,))).fetchall()
        return {"rarities": list(RARITIES), "items": [dict(row) for row in rows], "bundles": BUNDLES, "membership": {"name":"Bishoply Crown", "plans":CROWN_PLANS, "benefits":["Advanced reviews", "Expanded Lab tools", "Premium profile customization", "Member cosmetics"]}}
    finally: await connection.close()

async def checkout_status():
    if not os.getenv("STRIPE_SECRET_KEY"):
        raise HTTPException(503, "Shop checkout is not configured")
    raise HTTPException(503, "Shop checkout is not configured")

def _product(sku):
    for item in CATALOG:
        if item[0] == sku: return {"sku": sku, "name": item[1], "price_cents": item[5], "kind": "cosmetic"}
    for item in BUNDLES:
        if item["sku"] == sku: return {**item, "kind": "bundle"}
    for item in CROWN_PLANS:
        if item["sku"] == sku: return {**item, "kind": "subscription"}
    raise HTTPException(404, "Shop product not found")

async def create_checkout(user_id, sku, success_url, cancel_url):
    product = _product(sku)
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret: raise HTTPException(503, "Shop checkout is not configured")
    if product.get("price_cents", 0) <= 0: raise HTTPException(400, "This item does not require checkout")
    data = {"mode": "subscription" if product["kind"] == "subscription" else "payment", "success_url": success_url, "cancel_url": cancel_url, "client_reference_id": str(user_id), "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": "usd", "line_items[0][price_data][unit_amount]": str(product["price_cents"]), "line_items[0][price_data][product_data][name]": product["name"], "metadata[product_sku]": sku, "metadata[user_id]": str(user_id)}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post("https://api.stripe.com/v1/checkout/sessions", data=data, auth=(secret, ""))
    if response.status_code >= 400: raise HTTPException(502, "Payment provider unavailable")
    return response.json()

def verify_webhook(payload: bytes, signature: str):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret or not signature: raise HTTPException(400, "Webhook verification is not configured")
    timestamp, _, signatures = signature.partition(",")
    if not timestamp.startswith("t="): raise HTTPException(400, "Invalid webhook signature")
    expected = hmac.new(secret.encode(), (timestamp[2:] + "." ).encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, value[3:]) for value in signatures.split(",") if value.startswith("v1=")):
        raise HTTPException(400, "Invalid webhook signature")
    return json.loads(payload)

async def fulfill_webhook(event):
    event_id, event_type = event.get("id"), event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    user_id, sku = metadata.get("user_id"), metadata.get("product_sku")
    if not event_id or not user_id or not sku: return {"status": "ignored"}
    product = _product(sku); connection = await db.connect()
    try:
        existing = await (await connection.execute("SELECT id FROM commerce_transactions WHERE provider_event_id=?", (event_id,))).fetchone()
        if existing: return {"status": "already_processed"}
        await connection.execute("INSERT INTO commerce_transactions(provider,provider_event_id,user_id,product_sku,amount_cents,status) VALUES ('stripe',?,?,?,?,?)", (event_id, int(user_id), sku, product.get("price_cents"), "completed"))
        if product["kind"] == "cosmetic":
            row = await (await connection.execute("SELECT id FROM cosmetics WHERE sku=?", (sku,))).fetchone()
            if row: await connection.execute("INSERT OR IGNORE INTO user_cosmetics(user_id,cosmetic_id,source,transaction_id) VALUES (?,?,?,?)", (int(user_id), row["id"], "purchase", event_id))
        elif product["kind"] == "subscription":
            status = "active" if event_type in {"checkout.session.completed", "customer.subscription.created", "customer.subscription.updated"} else "cancelled"
            await connection.execute("INSERT OR REPLACE INTO subscriptions(user_id,provider,provider_subscription_id,plan_sku,status) VALUES (?,?,?,?,?)", (int(user_id), "stripe", obj.get("subscription") or obj.get("id"), sku, status))
        await connection.commit(); return {"status": "fulfilled"}
    except Exception: await connection.rollback(); raise
    finally: await connection.close()
