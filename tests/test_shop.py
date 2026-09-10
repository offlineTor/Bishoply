import tempfile
import unittest
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
