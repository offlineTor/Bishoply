import tempfile
import unittest
import os, json, hmac, hashlib, time
from pathlib import Path

from backend.database import db
from backend.services import shop


class ShopCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_path, self.old_url = db.DB_PATH, db.DATABASE_URL
        self.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp.name) / "shop.db"
        db.DATABASE_URL = ""
        await db.initialize_database()
        await shop.initialize()

    async def asyncTearDown(self):
        db.DB_PATH, db.DATABASE_URL = self.old_path, self.old_url
        self.temp.cleanup()

    async def test_catalog_is_idempotent_and_uses_bishoply_rarities(self):
        await shop.initialize()
        catalog = await shop.catalog()
        self.assertEqual(catalog["rarities"], ["Classic", "Refined", "Elite", "Mythic", "Eclipse"])
        self.assertGreaterEqual(len(catalog["items"]), 10)
        self.assertEqual(len({item["sku"] for item in catalog["items"]}), len(catalog["items"]))
        self.assertEqual(len(catalog["bundles"]), 4)
        self.assertEqual(catalog["membership"]["name"], "Bishoply Crown")

    async def test_webhook_signature_and_fulfillment_are_idempotent(self):
        connection = await db.connect()
        await connection.execute("INSERT INTO users(discord_id,username,username_normalized,display_name) VALUES (NULL,'buyer','buyer','Buyer')")
        await connection.commit(); await connection.close()
        await shop.initialize()
        payload = json.dumps({"id":"evt_test_1","type":"checkout.session.completed","data":{"object":{"metadata":{"user_id":"1","product_sku":"board-midnight-gold"}}}}).encode()
        old = os.environ.get("STRIPE_WEBHOOK_SECRET"); os.environ["STRIPE_WEBHOOK_SECRET"] = "test_secret"
        try:
            stamp = str(int(time.time())); digest = hmac.new(b"test_secret", (stamp+".").encode()+payload, hashlib.sha256).hexdigest()
            event = shop.verify_webhook(payload, f"t={stamp},v1={digest}")
            self.assertEqual((await shop.fulfill_webhook(event))["status"], "fulfilled")
            self.assertEqual((await shop.fulfill_webhook(event))["status"], "already_processed")
        finally:
            if old is None: os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
            else: os.environ["STRIPE_WEBHOOK_SECRET"] = old
