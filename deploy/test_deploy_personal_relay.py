import importlib.util
from contextlib import closing, contextmanager
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('deployment', pathlib.Path(__file__).with_name('deploy-personal-relay.py'))
deployment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployment)


@contextmanager
def connection(path):
    with closing(sqlite3.connect(path)) as database:
        with database:
            yield database

COMPOSE = b'''# exact comments preserved
services:
  openwebui:
    image: original-chat
    environment: {SENTINEL: "unchanged"}
  newapi:
    image: old-api
    env_file: [/data/existing-session.env]
    environment:
      SQLITE_PATH: /data/new-api.db
      CUSTOM_OAUTH_PKCE_PROVIDERS: pingxingxian
      CHANNEL_TEST_FREQUENCY: "0"
      GENERATE_DEFAULT_TOKEN: "false"
    volumes:
      - /data/api:/data
networks: {default: {}}
'''


class DeploymentTests(unittest.TestCase):
    def database(self, purpose_column=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = pathlib.Path(temp.name) / 'test.db'
        with connection(path) as db:
            db.execute('CREATE TABLE tokens (id INTEGER, deleted_at TEXT, status INTEGER' +
                       (', internal_purpose TEXT' if purpose_column else '') + ')')
        return path

    def test_minimal_compose_update_preserves_chat_and_env_file_bytes(self):
        result = deployment.render_compose(COMPOSE, 'old-api', 'new-api', True)
        expected = COMPOSE.replace(b'image: old-api', b'image: "new-api"').replace(
            b'    volumes:', b'      CHAT_OAUTH_RELAY_ENABLED: "true"\n    volumes:')
        self.assertEqual(result, expected)
        disabled = deployment.render_compose(result, 'new-api', 'new-api', False)
        self.assertEqual(disabled, result.replace(b'CHAT_OAUTH_RELAY_ENABLED: "true"', b'CHAT_OAUTH_RELAY_ENABLED: "false"'))

    def test_compose_rejects_missing_safety_flag_or_session_file(self):
        for source in [COMPOSE.replace(b'    env_file: [/data/existing-session.env]\n', b''),
                       COMPOSE.replace(b'CHANNEL_TEST_FREQUENCY: "0"', b'CHANNEL_TEST_FREQUENCY: "1"')]:
            with self.assertRaises(deployment.DeploymentError):
                deployment.render_compose(source, 'old-api', 'new-api', True)

    def test_old_schema_and_only_null_purpose_allow_rollback(self):
        self.assertTrue(deployment.rollback_allowed(self.database(False)))
        path = self.database()
        with connection(path) as db:
            db.execute('INSERT INTO tokens VALUES (1, NULL, 1, NULL)')
        self.assertTrue(deployment.rollback_allowed(path))

    def test_deleted_disabled_and_empty_nonnull_purpose_block_rollback(self):
        for purpose in ['chat-oauth-v1', '', 'future-internal-purpose']:
            path = self.database()
            with connection(path) as db:
                db.execute('INSERT INTO tokens VALUES (1, ?, 0, ?)', ('deleted', purpose))
            self.assertFalse(deployment.rollback_allowed(path))

    def test_missing_or_unreadable_schema_fails_closed(self):
        path = self.database()
        with connection(path) as db:
            db.execute('DROP TABLE tokens')
        self.assertFalse(deployment.rollback_allowed(path))
        self.assertFalse(deployment.rollback_allowed(path.with_name('absent.db')))

    def test_rollback_database_must_match_actual_container_bind(self):
        database = self.database()
        correct = database.parent / 'new-api.db'
        mounts = [{'Type': 'bind', 'Destination': '/data', 'Source': str(database.parent)}]
        deployment.verify_database_binding(COMPOSE, mounts, correct)
        with self.assertRaises(deployment.DeploymentError):
            deployment.verify_database_binding(COMPOSE, mounts, database)
        with self.assertRaises(deployment.DeploymentError):
            deployment.verify_database_binding(COMPOSE, [], correct)

    def test_recovery_freezes_minting_and_never_runs_old_image_with_purpose(self):
        path = self.database()
        config = path.with_name('compose.yaml')
        proposed = deployment.render_compose(COMPOSE, 'old-api', 'new-api', True)
        config.write_bytes(proposed)
        with connection(path) as db:
            db.execute('INSERT INTO tokens VALUES (1, ?, 0, ?)', ('deleted', 'chat-oauth-v1'))
        calls = []
        def compose(*args):
            calls.append((args, config.read_bytes()))
        with patch.object(deployment, 'wait_health'):
            state = deployment.recover({'database': str(path), 'compose': str(config), 'image': 'new-api'}, COMPOSE, proposed, compose)
        self.assertEqual(calls[0][0], ('stop', 'newapi'))
        self.assertEqual(state, 'pending_recovery_guarded_image_running_relay_disabled')
        self.assertTrue(all(b'old-api' not in data for args, data in calls if args[0] == 'up'))
        self.assertIn(b'CHAT_OAUTH_RELAY_ENABLED: "false"', config.read_bytes())
        self.assertEqual(deployment.internal_token_count(path), 1)

    def test_failed_stop_does_not_read_guard_or_change_config(self):
        with patch.object(deployment, 'rollback_allowed') as guard:
            def fail(*args):
                raise deployment.DeploymentError('stop_failed')
            self.assertEqual(deployment.recover({}, COMPOSE, COMPOSE, fail), 'pending_recovery_stop_failed')
            guard.assert_not_called()


if __name__ == '__main__':
    unittest.main()
