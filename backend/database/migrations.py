"""Explicit schema version metadata for SQLite and PostgreSQL deployments."""

SCHEMA_VERSION = 1
DISCORD_ID_MIGRATION_VERSION = 2
PRACTICE_IDENTITY_MIGRATION_VERSION = 3


async def current_version(db):
    try:
        row = await (await db.execute("SELECT MAX(version) AS version FROM schema_migrations")).fetchone()
        return int(row["version"] or 0) if row else 0
    except Exception:
        return 0


async def record_version(db, version=SCHEMA_VERSION):
    await db.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (version,))
    await db.commit()
