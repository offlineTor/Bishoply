"""Legacy TEXT timestamp cleanup, including an isolated real PostgreSQL case."""
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import chess

from backend.database import db as database
from backend.practice import storage


class PracticeCleanupTimestampTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.enterContext(patch.object(database, 'DATABASE_URL', ''))
        self.enterContext(patch.object(database, 'DB_PATH', Path(self.directory.name) / 'cleanup.db'))
        await self.seed_legacy_games()

    async def seed_legacy_games(self):
        connection = await database.connect()
        try:
            # Only the canonical-user dependency is needed for Practice init.
            await connection.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, discord_id BIGINT UNIQUE)')
            await connection.execute('INSERT INTO users VALUES (?,?)', (1, 1546225609967935620))
            await connection.executescript(storage.SCHEMA)
            self.saved_timestamp = '2025-01-01T12:34:56+00:00'
            for index in range(8):
                # Seven active games and a completed result which must not change.
                await connection.execute('''INSERT INTO practice_games
                    (public_id,owner_user_id,owner_discord_id,access_hash,player_color,
                     bot_id,bot_strength,bot_personality,bot_config,starting_fen,current_fen,
                     status,result,termination_reason,created_at,updated_at,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (f'cleanup_{index}', 1 if index % 2 else None, 1546225609967935620,
                     'test-hash', 'white', 'scout', 600, 'forgiving', '{}',
                     chess.STARTING_FEN, chess.STARTING_FEN,
                     'active' if index < 7 else 'black_win', None if index < 7 else '0-1',
                     None if index < 7 else 'resignation',
                     f'2025-01-{index + 1:02d} 00:00:00', '2025-01-01 00:00:00',
                     self.saved_timestamp if index in (0, 7) else None))
            game = await (await connection.execute(
                "SELECT id FROM practice_games WHERE public_id='cleanup_0'")).fetchone()
            board = chess.Board()
            board.push_uci('e2e4')
            await connection.execute('''INSERT INTO practice_moves
                (game_id,ply,move_number,color,actor,uci,san,fen_after)
                VALUES (?,1,1,'white','player','e2e4','e4',?)''', (game['id'], board.fen()))
            await connection.execute('UPDATE practice_games SET ply=1,current_fen=? WHERE id=?',
                                     (board.fen(), game['id']))
            await connection.commit()
        finally:
            await connection.close()

    async def snapshot(self):
        connection = await database.connect()
        try:
            games = await (await connection.execute('SELECT * FROM practice_games ORDER BY id')).fetchall()
            moves = await (await connection.execute('SELECT * FROM practice_moves ORDER BY id')).fetchall()
            return [dict(row) for row in games], [dict(row) for row in moves]
        finally:
            await connection.close()

    async def exercise_cleanup(self, startup):
        before, moves_before = await self.snapshot()

        async def run():
            if startup:
                await storage.initialize()
            else:
                connection = await database.connect()
                try:
                    kept = await storage.cleanup_active_games(connection, 1, 1546225609967935620)
                    self.assertEqual(kept['public_id'], 'cleanup_6')
                    await connection.commit()
                finally:
                    await connection.close()

        await run()
        after, moves_after = await self.snapshot()
        self.assertEqual(len(after), 8)
        self.assertEqual(moves_before, moves_after)
        self.assertEqual(after[7], before[7])
        self.assertEqual([row['public_id'] for row in after if row['status'] == 'active'], ['cleanup_6'])
        self.assertIsNone(after[6]['completed_at'])
        for index, row in enumerate(after[:6]):
            self.assertEqual(row['termination_reason'], 'superseded')
            self.assertEqual(row['status'], 'draw')
            self.assertIsNone(row['result'])
            self.assertEqual(row['current_fen'], before[index]['current_fen'])
            self.assertEqual(row['ply'], before[index]['ply'])
            # This fails on the old SQLite-tolerated CURRENT_TIMESTAMP SQL,
            # too: cleanup must write an explicitly UTC ISO string.
            self.assertEqual(datetime.fromisoformat(row['updated_at']).tzinfo, timezone.utc)
            if index == 0:
                self.assertEqual(row['completed_at'], self.saved_timestamp)
            else:
                self.assertEqual(row['completed_at'], row['updated_at'])
        await run()
        self.assertEqual(await self.snapshot(), (after, moves_after))

    async def test_cleanup_text_timestamps_preserves_history_and_is_idempotent(self):
        await self.exercise_cleanup(startup=False)

    async def test_repeated_startup_with_seven_active_games(self):
        await self.exercise_cleanup(startup=True)


class PostgreSQLPracticeCleanupTimestampTests(PracticeCleanupTimestampTests):
    async def asyncSetUp(self):
        url = os.getenv('TEST_DATABASE_URL')
        if not url:
            self.skipTest('TEST_DATABASE_URL not configured; real PostgreSQL cleanup test')
        import psycopg
        from psycopg import sql

        # Never use or modify existing application tables in the test database.
        schema = 'practice_cleanup_test_' + uuid.uuid4().hex
        admin = await psycopg.AsyncConnection.connect(url, autocommit=True)
        self.addAsyncCleanup(admin.close)
        await admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

        async def drop_schema():
            await admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        self.addAsyncCleanup(drop_schema)

        async def connect():
            raw = await psycopg.AsyncConnection.connect(
                url, options=f'-c search_path={schema}', row_factory=database._compat_row_factory)
            return database.PostgresCompatConnection(raw)

        async def columns(connection, table):
            # Production introspection is public-schema scoped. Isolate only
            # that lookup to our disposable schema; run all init/cleanup SQL.
            rows = await (await connection.execute('''SELECT column_name AS name
                FROM information_schema.columns WHERE table_schema=? AND table_name=?''',
                (schema, table))).fetchall()
            return {row['name'] for row in rows}

        self.enterContext(patch.object(database, 'connect', connect))
        self.enterContext(patch.object(database, 'using_postgres', return_value=True))
        self.enterContext(patch.object(database, 'get_table_columns', columns))
        await self.seed_legacy_games()
        connection = await connect()
        try:
            types = await (await connection.execute('''SELECT column_name,data_type
                FROM information_schema.columns WHERE table_schema=? AND table_name='practice_games'
                AND column_name IN ('completed_at','created_at','updated_at')''', (schema,))).fetchall()
            self.assertEqual(len(types), 3)
            self.assertTrue(all(row['data_type'] == 'text' for row in types))
        finally:
            await connection.close()


if __name__ == '__main__':
    unittest.main()
