import tempfile, unittest
from pathlib import Path
from backend.database import db
from backend.services.game_service import create_private_game_for_user, join_private_game_for_user

class PrivateGameTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.old_path,self.old_url=db.DB_PATH,db.DATABASE_URL; self.temp=tempfile.TemporaryDirectory(); db.DB_PATH=Path(self.temp.name)/"games.db"; db.DATABASE_URL=""; await db.initialize_database(); c=await db.connect(); await c.execute("INSERT INTO users(discord_id,username,username_normalized) VALUES(NULL,'a','a')"); await c.execute("INSERT INTO users(discord_id,username,username_normalized) VALUES(NULL,'b','b')"); await c.commit(); await c.close()
 async def asyncTearDown(self): db.DB_PATH,db.DATABASE_URL=self.old_path,self.old_url; self.temp.cleanup()
 async def test_private_create_and_join_is_platform_neutral(self):
  created=await create_private_game_for_user(1); self.assertTrue(created["code"])
  joined=await join_private_game_for_user(created["code"],2); self.assertEqual(joined["game"]["status"],"active")
  self.assertNotEqual(joined["game"]["white"]["id"], joined["game"]["black"]["id"])
