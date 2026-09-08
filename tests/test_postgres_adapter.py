import os
import unittest


class PostgreSQLIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Runs against a real local/staging PostgreSQL when TEST_DATABASE_URL is set."""

    def test_row_factory_is_safe_for_ddl_cursors(self):
        from backend.database.db import _compat_row_factory

        class Cursor:
            description = None

        self.assertTrue(callable(_compat_row_factory(Cursor())))

    async def test_postgres_round_trip(self):
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            self.skipTest("TEST_DATABASE_URL not configured; PostgreSQL integration is environment-gated")
        from backend.database import db
        self.assertTrue(url.startswith(("postgres://", "postgresql://")))
        old = db.DATABASE_URL
        db.DATABASE_URL = url
        try:
            conn = await db.connect()
            row = await (await conn.execute("SELECT 1 AS ok")).fetchone()
            self.assertEqual(row["ok"], 1)
            await conn.close()
        finally:
            db.DATABASE_URL = old


if __name__ == "__main__":
    unittest.main()
