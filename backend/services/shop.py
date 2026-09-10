"""Server-authoritative Bishoply cosmetic catalog and Crown configuration."""
import os
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
