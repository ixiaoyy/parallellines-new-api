#!/usr/bin/env python3
"""Read-only, fail-closed check before rolling back to NewAPI pkce.1.

This checks only schema and the existence of internal-purpose token rows. It
never reads token keys, changes rows, or authorizes a rollback by itself.
"""

import argparse
from pathlib import Path
import sqlite3
import sys


LEGACY_WARNING = "pkce.1 has no internal-purpose token guard."


def check_database(database):
    """Return (allowed, explanation), without exposing paths or SQL errors."""
    connection = None
    try:
        # URI mode=ro prevents sqlite3 from creating a missing database. as_uri
        # escapes path characters such as '?' and '#' instead of treating them
        # as SQLite URI parameters.
        uri = Path(database).resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'tokens' COLLATE NOCASE LIMIT 1"
        ).fetchone()
        if table is None:
            return False, "DENY: tokens table is missing; inspection is incomplete. " + LEGACY_WARNING
        columns = connection.execute('PRAGMA table_info("tokens")').fetchall()
        if not columns:
            return False, "DENY: tokens schema could not be inspected. " + LEGACY_WARNING
        if not any(str(column[1]).lower() == "internal_purpose" for column in columns):
            return True, "ALLOW: legacy tokens schema has no internal_purpose column. " + LEGACY_WARNING
        internal = connection.execute(
            'SELECT EXISTS (SELECT 1 FROM "tokens" '
            'WHERE "internal_purpose" IS NOT NULL LIMIT 1)'
        ).fetchone()
        if internal is None:
            return False, "DENY: token inspection did not return a result. " + LEGACY_WARNING
        if internal[0]:
            return False, "DENY: internal-purpose token rows exist, including any disabled or deleted rows. " + LEGACY_WARNING
        return True, "ALLOW: no internal-purpose token rows exist. " + LEGACY_WARNING
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        return False, "DENY: database is unavailable or read-only inspection failed. " + LEGACY_WARNING
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                return False, "DENY: read-only inspection could not finish cleanly. " + LEGACY_WARNING


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only rollback guard: pkce.1 has no internal-purpose token guard."
    )
    parser.add_argument("database", help="SQLite database file to inspect (opened mode=ro)")
    args = parser.parse_args(argv)
    allowed, explanation = check_database(args.database)
    print(explanation)
    return 0 if allowed else 2


if __name__ == "__main__":
    sys.exit(main())
