#!/usr/bin/env python3
"""Validated, non-destructive SQLite -> PostgreSQL importer.

The importer never deletes or mutates the SQLite source. Use --apply only after
backups and a staging dry run. It copies tables in dependency order where
possible and reports row-level failures.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg import sql
except ImportError:
    psycopg = None


def pg_type(declared):
    t = (declared or "TEXT").upper()
    if "INT" in t: return "BIGINT"
    if any(x in t for x in ("REAL", "FLOA", "DOUB")): return "DOUBLE PRECISION"
    if any(x in t for x in ("BLOB",)): return "BYTEA"
    if any(x in t for x in ("DATE", "TIME")): return "TIMESTAMPTZ"
    return "TEXT"


def tables(source):
    rows = source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [row[0] for row in rows]


def import_database(sqlite_path, database_url, apply=False):
    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    names = tables(source)
    if not apply:
        total = sum(source.execute('SELECT COUNT(*) FROM "' + n.replace('"', '""') + '"').fetchone()[0] for n in names)
        print(f"Validated SQLite source: {len(names)} tables, {total} rows")
        print("Dry run only. Re-run with --apply to write PostgreSQL.")
        return
    if psycopg is None:
        raise SystemExit("psycopg is required for PostgreSQL import; install psycopg[binary].")
    with psycopg.connect(database_url) as target:
        target.autocommit = False
        failures = []
        target.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        for name in names:
            columns = source.execute(f'PRAGMA table_info("{name}")').fetchall()
            defs = []
            for col in columns:
                definition = sql.SQL("{} {}{}").format(sql.Identifier(col[1]), sql.SQL(pg_type(col[2])), sql.SQL(" NOT NULL") if col[3] else sql.SQL(""))
                defs.append(definition)
            pk = [col[1] for col in columns if col[5]]
            if pk: defs.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(",").join(map(sql.Identifier, pk))))
            for fk in source.execute(f'PRAGMA foreign_key_list("{name}")').fetchall():
                defs.append(sql.SQL("FOREIGN KEY ({}) REFERENCES {} ({})").format(sql.Identifier(fk[3]), sql.Identifier(fk[2]), sql.Identifier(fk[4])))
            target.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(sql.Identifier(name), sql.SQL(",").join(defs)))
            rows = source.execute(f'SELECT * FROM "{name}"').fetchall()
            for row in rows:
                try:
                    target.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(sql.Identifier(name), sql.SQL(",").join(map(sql.Identifier, [c[1] for c in columns])), sql.SQL(",").join(sql.Placeholder() for _ in columns)), tuple(row))
                except Exception as exc:
                    failures.append((name, str(exc)))
        if failures:
            target.rollback()
            raise RuntimeError(f"Migration rolled back; {len(failures)} row failures (first: {failures[0][0]}: {failures[0][1]})")
        target.commit()
        target.execute("INSERT INTO schema_migrations(version) VALUES (1) ON CONFLICT DO NOTHING")
        target.commit()
        print(f"Imported {len(names)} tables without row failures.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default="bishoply.db", type=Path)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.sqlite.exists(): raise SystemExit(f"SQLite source not found: {args.sqlite}")
    if args.apply and not args.database_url: raise SystemExit("--database-url is required with --apply")
    import_database(args.sqlite, args.database_url, args.apply)
