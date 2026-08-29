"""
One-off runner: applies a given .sql migration file directly against the
Supabase Postgres database via SUPABASE_DB_URL (not the REST API, which
can't run DDL). Never prints the connection string or any credential.

Usage:
    python scripts/run_migration.py supabase/migrations/0002_add_contact_phone.sql
"""

from __future__ import annotations

import os
import re
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def _strip_bracketed_password(db_url: str) -> str:
    """
    Auto-fix a common copy/paste mistake: keeping the literal [ ] template
    markers around the password instead of replacing them along with the
    placeholder text, e.g. postgres:[hunter2]@host -> postgres:hunter2@host.
    """

    return re.sub(
        r"(postgresql://[^:]+:)\[([^\]]+)\](@)",
        r"\1\2\3",
        db_url,
    )


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_migration.py <path-to-sql-file>")
        sys.exit(1)

    sql_path = sys.argv[1]

    db_url = os.getenv("SUPABASE_DB_URL")

    if not db_url:
        print("SUPABASE_DB_URL is not set in .env")
        sys.exit(1)

    db_url = _strip_bracketed_password(db_url)

    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = None

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True

        with conn.cursor() as cur:
            cur.execute(sql)

        print(f"Migration applied successfully: {sql_path}")

    except Exception as exc:
        message = str(exc).replace(db_url, "[REDACTED]")
        print(f"Migration failed: {type(exc).__name__}: {message}")
        sys.exit(1)

    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
