import tempfile, unittest, asyncio
from pathlib import Path
from backend.database import db
from backend.services.game_service import create_private_game_for_user, join_private_game_for_user, get_game, make_move
from backend.services.competitive import ensure_player

class PrivateGameTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.old_path,self.old_url=db.DB_PATH,db.DATABASE_URL; self.temp=tempfile.TemporaryDirectory(); db.DB_PATH=Path(self.temp.name)/"games.db"; db.DATABASE_URL=""; await db.initialize_database(); c=await db.connect()
  for i in range(1,11): await c.execute("INSERT INTO users(discord_id,username,username_normalized) VALUES(NULL,?,?)", (f'u{i}',f'u{i}'))
  await c.commit(); await c.close()
 async def asyncTearDown(self): db.DB_PATH,db.DATABASE_URL=self.old_path,self.old_url; self.temp.cleanup()
 async def test_private_create_and_join_is_platform_neutral(self):
  created=await create_private_game_for_user(1); self.assertTrue(created["code"])
  joined=await join_private_game_for_user(created["code"],2); self.assertEqual(joined["game"]["status"],"active")
  self.assertNotEqual(joined["game"]["white"]["id"], joined["game"]["black"]["id"])

 async def test_all_platform_private_lifecycles(self):
  for index, (creator_platform, joiner_platform) in enumerate((("web","web"),("web","discord"),("discord","web"),("discord","discord"))):
   creator, joiner = index * 2 + 1, index * 2 + 2
   await ensure_player(creator_platform, f"{creator_platform}-{creator}", creator); await ensure_player(joiner_platform, f"{joiner_platform}-{joiner}", joiner)
   created=await create_private_game_for_user(creator); joined=await join_private_game_for_user(created["code"],joiner); game_id=joined["game"]["game_id"]
   state = (await get_game(game_id))["game"]
   self.assertNotEqual(state["white"]["id"], state["black"]["id"])
   self.assertTrue((await make_move(game_id,creator,"e2e4"))["ok"])
   self.assertEqual(len((await get_game(game_id))["game"]["moves"]), 1)
   self.assertTrue((await make_move(game_id,joiner,"e7e5"))["ok"])
   self.assertEqual(len((await get_game(game_id))["game"]["moves"]),2)
   self.assertFalse((await make_move(game_id, 10, "d2d4"))["ok"])

 async def test_private_final_seat_race(self):
  created=await create_private_game_for_user(1)
  results=await asyncio.gather(join_private_game_for_user(created["code"],2), join_private_game_for_user(created["code"],3), return_exceptions=True)
  successes=[r for r in results if isinstance(r,dict) and r.get("ok")]
  self.assertEqual(len(successes),1)
  game=(await get_game(created["code"]))["game"]
  self.assertIsNotNone(game["white"]); self.assertIsNotNone(game["black"])
