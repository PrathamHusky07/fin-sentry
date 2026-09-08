from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def run(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(_CREATE_TRACKING)

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            filename = path.name
            already_applied = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE filename = %s",
                (filename,),
            ).fetchone()
            if already_applied is not None:
                continue

            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (filename,),
                )


if __name__ == "__main__":
    load_dotenv()
    run(os.environ["DATABASE_URL"])
