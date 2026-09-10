import tempfile, unittest
from pathlib import Path
from backend.database import db
from backend.services import lab

class LabTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_path,self.old_url=db.DB_PATH,db.DATABASE_URL; self.temp=tempfile.TemporaryDirectory(); db.DB_PATH=Path(self.temp.name)/"lab.db"; db.DATABASE_URL=""; await db.initialize_database()
        c=await db.connect(); await c.execute("INSERT INTO users(discord_id,username,username_normalized) VALUES (NULL,'labuser','labuser')"); await c.commit(); await c.close()
    async def asyncTearDown(self): db.DB_PATH,db.DATABASE_URL=self.old_path,self.old_url; self.temp.cleanup()
    async def test_saved_lab_positions_are_owned_and_not_games(self):
        saved=await lab.create(1,"Tactic", "8/8/8/8/8/8/4K3/4k3 w - - 0 1")
        self.assertEqual(len(await lab.list_for_user(1)),1)
        self.assertEqual((await lab.delete(1,saved["id"]))["deleted"],True)
