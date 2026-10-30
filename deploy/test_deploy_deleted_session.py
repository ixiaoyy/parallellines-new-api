import importlib.util
import json
import pathlib
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch

import yaml

SPEC = importlib.util.spec_from_file_location('deleted_session_deployment', pathlib.Path(__file__).with_name('deploy-deleted-session.py'))
deployment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployment)

COMPOSE = b'''# preserve every unrelated service and environment value
services:
  openwebui:
    image: original-chat
    environment: {SENTINEL: "unchanged"}
  newapi:
    image: parallellines-newapi:v0.13.2-pkce.4
    env_file: [/data/existing-session.env]
    environment:
      SQLITE_PATH: /data/new-api.db
      CUSTOM_OAUTH_PKCE_PROVIDERS: pingxingxian
      CHANNEL_TEST_FREQUENCY: "0"
      GENERATE_DEFAULT_TOKEN: "false"
      OPENAI_STANDARD_BILLING_ENABLED: "true"
      MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"
      CHAT_OAUTH_RELAY_ENABLED: "true"
      UNRELATED: preserve-this
    volumes:
      - /data/api:/data
networks: {default: {}}
'''


class DeletedSessionDeploymentTests(unittest.TestCase):
    def config(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        compose = pathlib.Path(temporary.name) / 'compose.yaml'
        proposed = deployment.render_compose(COMPOSE, deployment.OLD_IMAGE)
        compose.write_bytes(proposed)
        return compose, proposed

    def test_normal_activation_changes_only_image(self):
        proposed = deployment.render_compose(COMPOSE, deployment.OLD_IMAGE)
        expected = COMPOSE.replace(b'image: parallellines-newapi:v0.13.2-pkce.4', b'image: "parallellines-newapi:v0.13.2-pkce.5"')
        self.assertEqual(proposed, expected)
        old, new = yaml.safe_load(COMPOSE), yaml.safe_load(proposed)
        self.assertEqual(old['services']['newapi']['environment'], new['services']['newapi']['environment'])
        self.assertEqual(old['services']['openwebui'], new['services']['openwebui'])

    def test_required_existing_flags_and_exact_release_pair(self):
        for key in (b'OPENAI_STANDARD_BILLING_ENABLED', b'MAIN_OAUTH_PROFILE_SYNC_ENABLED', b'CHAT_OAUTH_RELAY_ENABLED'):
            for value in (b'false', b'invalid'):
                with self.assertRaises(deployment.DeploymentError):
                    deployment.render_compose(COMPOSE.replace(key + b': "true"', key + b': "' + value + b'"'), deployment.OLD_IMAGE)
        with patch.object(deployment.base, 'validate_scope'):
            deployment.validate_scope({'expected_image': deployment.OLD_IMAGE, 'image': deployment.NEW_IMAGE, 'version': deployment.VERSION})
            for old, new, version in [('parallellines-newapi:v0.13.2-pkce.3', deployment.NEW_IMAGE, deployment.VERSION),
                                      (deployment.OLD_IMAGE, deployment.OLD_IMAGE, deployment.VERSION),
                                      (deployment.OLD_IMAGE, deployment.NEW_IMAGE, 'v0.13.2-pkce.6')]:
                with self.assertRaises(deployment.DeploymentError):
                    deployment.validate_scope({'expected_image': old, 'image': new, 'version': version})

    def test_recovery_changes_only_relay_flag_on_new_image(self):
        proposed = deployment.render_compose(COMPOSE, deployment.OLD_IMAGE)
        disabled = deployment.render_compose(proposed, deployment.NEW_IMAGE, False)
        self.assertEqual(disabled, proposed.replace(b'CHAT_OAUTH_RELAY_ENABLED: "true"', b'CHAT_OAUTH_RELAY_ENABLED: "false"'))

    def test_stop_requires_actual_running_false(self):
        calls = []
        with patch.object(deployment.base, 'run', return_value='true'):
            with self.assertRaisesRegex(deployment.DeploymentError, 'newapi_stop_not_confirmed'):
                deployment.stop_and_verify({'container': 'fixture'}, lambda *args: calls.append(args))
        self.assertEqual(calls, [('stop', 'newapi')])
        with patch.object(deployment.base, 'run', return_value='false'):
            deployment.stop_and_verify({'container': 'fixture'}, lambda *args: calls.append(args))

    def test_backup_preserves_source_users_provider_secret_and_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / 'source.db'
            destination = pathlib.Path(temporary) / 'backup.db'
            with closing(sqlite3.connect(source)) as connection:
                connection.execute('CREATE TABLE users(id INTEGER, role INTEGER, quota INTEGER)')
                connection.execute('INSERT INTO users VALUES(1,100,0),(2,100,999)')
                connection.execute('CREATE TABLE custom_oauth_providers(id INTEGER, scopes TEXT, client_secret TEXT)')
                connection.execute("INSERT INTO custom_oauth_providers VALUES(1,'openid profile email','synthetic-secret')")
                connection.execute('CREATE TABLE logs(id INTEGER, content TEXT)')
                connection.execute("INSERT INTO logs VALUES(1,'synthetic-audit')")
                connection.commit()
            before = source.read_bytes()
            deployment.backup_database(source, destination)
            self.assertEqual(source.read_bytes(), before)
            with closing(sqlite3.connect(destination)) as connection:
                self.assertEqual(connection.execute('SELECT * FROM users').fetchall(), [(1, 100, 0), (2, 100, 999)])
                self.assertEqual(connection.execute('SELECT * FROM custom_oauth_providers').fetchall(), [(1, 'openid profile email', 'synthetic-secret')])
                self.assertEqual(connection.execute('SELECT * FROM logs').fetchall(), [(1, 'synthetic-audit')])

    def test_recovery_is_forward_only_without_database_access(self):
        compose, proposed = self.config()
        calls = []
        def command(*args):
            calls.append((args, compose.read_bytes()))
        with patch.object(deployment.base, 'run', return_value='false'), \
             patch.object(deployment.base, 'wait_health'), patch.object(deployment, 'verify_runtime'), \
             patch.object(deployment.sqlite3, 'connect', side_effect=AssertionError('No DB access during recovery')):
            state = deployment.recover({'compose': str(compose), 'container': 'fixture'}, COMPOSE, proposed, command)
        self.assertEqual(state, 'pending_recovery_pkce5_policies_retained_relay_disabled')
        for args, data in calls:
            if args[0] == 'up':
                self.assertIn(deployment.NEW_IMAGE.encode(), data)
                self.assertNotIn(deployment.OLD_IMAGE.encode(), data)
                self.assertIn(b'CHAT_OAUTH_RELAY_ENABLED: "false"', data)
                self.assertIn(b'MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"', data)
                self.assertIn(b'OPENAI_STANDARD_BILLING_ENABLED: "true"', data)

    def test_unconfirmed_stop_and_concurrent_compose_are_preserved(self):
        compose, proposed = self.config()
        with patch.object(deployment.base, 'run', return_value='true'):
            state = deployment.recover({'compose': str(compose), 'container': 'fixture'}, COMPOSE, proposed, lambda *args: None)
        self.assertEqual(state, 'pending_recovery_stop_unconfirmed')
        self.assertEqual(compose.read_bytes(), proposed)
        changed = proposed + b'# concurrent operator change\n'
        compose.write_bytes(changed)
        with patch.object(deployment.base, 'run', return_value='false'):
            state = deployment.recover({'compose': str(compose), 'container': 'fixture'}, COMPOSE, proposed, lambda *args: None)
        self.assertEqual(state, 'pending_recovery_concurrent_compose_change_preserved')
        self.assertEqual(compose.read_bytes(), changed)

    def test_failed_new_image_is_stopped_not_rolled_back(self):
        compose, proposed = self.config()
        calls = []
        def command(*args):
            calls.append(args)
            if args[0] == 'up':
                raise deployment.DeploymentError('synthetic_start_failure')
        with patch.object(deployment.base, 'run', return_value='false'):
            state = deployment.recover({'compose': str(compose), 'container': 'fixture'}, COMPOSE, proposed, command)
        self.assertEqual(state, 'pending_recovery_pkce5_stopped_operator_required')
        self.assertEqual(calls[-1], ('stop', 'newapi'))
        self.assertNotIn(deployment.OLD_IMAGE.encode(), compose.read_bytes())

    def test_runtime_checks_all_existing_safety_flags_without_printing_env(self):
        calls = []
        def run(args):
            calls.append(args)
            return deployment.NEW_IMAGE if args[1] == 'inspect' else ''
        with patch.object(deployment.base, 'run', side_effect=run):
            deployment.verify_runtime({'container': 'fixture'}, False)
        script = calls[-1][-1]
        for fragment in ('MAIN_OAUTH_PROFILE_SYNC_ENABLED" = true', 'OPENAI_STANDARD_BILLING_ENABLED" = true',
                         'CHAT_OAUTH_RELAY_ENABLED" = false', 'GENERATE_DEFAULT_TOKEN" = false'):
            self.assertIn(fragment, script)
        self.assertNotIn('printenv', script)

    def test_isolated_smoke_cannot_access_network_accounts_or_persistent_data(self):
        calls = []
        def run(args):
            calls.append(args)
            if args[:2] == ['docker', 'run']:
                return 'temporary-fixture'
            if args[-1].endswith('/api/status'):
                return json.dumps({'success': True, 'data': {'version': deployment.VERSION}})
            if args[-1].endswith('/api/setup'):
                return json.dumps({'success': True, 'data': {'root_init': False}})
            return ''
        with patch.object(deployment.base, 'run', side_effect=run):
            deployment.isolated_smoke()
        self.assertIn('--network=none', calls[0])
        self.assertIn('--read-only', calls[0])
        self.assertIn('GENERATE_DEFAULT_TOKEN=false', calls[0])
        self.assertIn('CHAT_OAUTH_RELAY_ENABLED=false', calls[0])
        self.assertNotIn('-v', calls[0])
        self.assertEqual(calls[-1], ['docker', 'rm', '-f', 'temporary-fixture'])


if __name__ == '__main__':
    unittest.main()
