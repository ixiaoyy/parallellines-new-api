"""Synthetic SQLite tests; no production paths, credentials, or services."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "guard_legacy_rollback", Path(__file__).with_name("guard-legacy-rollback.py")
)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class LegacyRollbackGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "synthetic # database.sqlite"

    def create_database(self, legacy=False, rows=()):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            if legacy:
                connection.execute("CREATE TABLE tokens (id INTEGER PRIMARY KEY, key TEXT)")
            else:
                connection.execute(
                    "CREATE TABLE tokens (id INTEGER PRIMARY KEY, key TEXT, "
                    "internal_purpose TEXT, status INTEGER, deleted_at TEXT)"
                )
                connection.executemany(
                    "INSERT INTO tokens (key, internal_purpose, status, deleted_at) VALUES (?, ?, ?, ?)",
                    [("synthetic-key-do-not-output", *row) for row in rows],
                )
            connection.commit()

    def assert_result(self, allowed):
        before = self.database.read_bytes() if self.database.is_file() else None
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = GUARD.main([str(self.database)])
        self.assertEqual(code, 0 if allowed else 2)
        text = output.getvalue()
        self.assertTrue(text.startswith("ALLOW:" if allowed else "DENY:"))
        self.assertIn("pkce.1 has no internal-purpose token guard", text)
        self.assertNotIn(str(self.database), text)
        self.assertNotIn("synthetic-key-do-not-output", text)
        if before is not None:
            self.assertEqual(self.database.read_bytes(), before)

    def test_legacy_schema_allowed(self):
        self.create_database(legacy=True)
        self.assert_result(True)

    def test_empty_current_table_allowed(self):
        self.create_database()
        self.assert_result(True)

    def test_normal_null_purpose_tokens_allowed(self):
        self.create_database(rows=[(None, 1, None), (None, 2, "synthetic-deleted-time")])
        self.assert_result(True)

    def test_any_non_null_purpose_denied_including_disabled_deleted_and_empty(self):
        for purpose, status, deleted_at in [
            ("chat-oauth-v1", 1, None),
            ("chat-oauth-v1", 2, None),
            ("chat-oauth-v1", 1, "synthetic-deleted-time"),
            ("chat-oauth-v1", 2, "synthetic-deleted-time"),
            ("future-internal-purpose", 1, None),
            ("", 1, None),
        ]:
            with self.subTest(purpose=purpose, status=status, deleted=deleted_at is not None):
                self.create_database(rows=[(None, 1, None), (purpose, status, deleted_at)])
                self.assert_result(False)
                self.database.unlink()

    def test_missing_file_denied_without_creating_it(self):
        self.assert_result(False)
        self.assertFalse(self.database.exists())

    def test_missing_tokens_table_denied(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE unrelated (id INTEGER)")
        self.assert_result(False)

    def test_view_named_tokens_does_not_pass_as_table(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE VIEW tokens AS SELECT NULL AS internal_purpose")
        self.assert_result(False)

    def test_corrupt_database_denied_without_error_details(self):
        self.database.write_bytes(b"synthetic-not-a-sqlite-database")
        self.assert_result(False)

    def test_query_error_denied_without_error_details(self):
        self.create_database()
        with mock.patch.object(GUARD.sqlite3, "connect") as connect:
            connect.return_value.execute.side_effect = sqlite3.OperationalError(
                "synthetic-key-do-not-output " + str(self.database)
            )
            self.assert_result(False)

    def test_connection_is_read_only_and_queries_never_read_keys(self):
        self.create_database(rows=[(None, 1, None)])
        original_connect = sqlite3.connect
        statements = []

        def tracked_connect(database_uri, **kwargs):
            self.assertTrue(database_uri.endswith("?mode=ro"))
            self.assertIn("%23", database_uri)
            self.assertTrue(kwargs["uri"])
            connection = original_connect(database_uri, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        with mock.patch.object(GUARD.sqlite3, "connect", side_effect=tracked_connect):
            self.assert_result(True)
        self.assertTrue(statements)
        for statement in statements:
            self.assertNotIn("key", statement.lower())
            self.assertNotIn("select *", statement.lower())


if __name__ == "__main__":
    unittest.main()
