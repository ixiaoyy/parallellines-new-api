import importlib.util
import json
import pathlib
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch

import yaml

SPEC = importlib.util.spec_from_file_location('profile_deployment', pathlib.Path(__file__).with_name('deploy-profile-sync.py'))
deployment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployment)

COMPOSE = b'''# preserve comment and unrelated service bytes
services:
  openwebui:
    image: original-chat
    environment: {SENTINEL: "unchanged"}
  newapi:
    image: parallellines-newapi:v0.13.2-pkce.3
    env_file: [/data/existing-session.env]
    environment:
      SQLITE_PATH: /data/new-api.db
      CUSTOM_OAUTH_PKCE_PROVIDERS: pingxingxian
      CHANNEL_TEST_FREQUENCY: "0"
      GENERATE_DEFAULT_TOKEN: "false"
      OPENAI_STANDARD_BILLING_ENABLED: "true"
      CHAT_OAUTH_RELAY_ENABLED: "true"
    volumes:
      - /data/api:/data
networks: {default: {}}
'''


class ProfileDeploymentTests(unittest.TestCase):
    def provider_database(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        database = pathlib.Path(temp.name) / 'provider.db'
        with closing(sqlite3.connect(database)) as connection:
            fields = ','.join(name + (' INTEGER' if isinstance(value, int) else ' TEXT')
                              for name, value in deployment.PROVIDER.items())
            connection.execute('CREATE TABLE custom_oauth_providers (' + fields + ', scopes TEXT, client_secret TEXT)')
            values = [*deployment.PROVIDER.values(), 'openid profile', 'synthetic-test-secret']
            connection.execute('INSERT INTO custom_oauth_providers VALUES (' + ','.join('?' for _ in values) + ')', values)
            connection.execute('CREATE TABLE users (id INTEGER, quota INTEGER, role INTEGER, display_name TEXT)')
            connection.execute("INSERT INTO users VALUES (2,0,100,'unchanged fixture')")
            connection.commit()
        return database

    def test_provider_scope_exact_cas_preserves_secret_and_users(self):
        database = self.provider_database()
        deployment.verify_provider(database)
        deployment.update_provider_scope(str(database))
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute('SELECT scopes,client_secret FROM custom_oauth_providers').fetchone(),
                             ('openid profile email', 'synthetic-test-secret'))
            self.assertEqual(connection.execute('SELECT * FROM users').fetchall(), [(2, 0, 100, 'unchanged fixture')])
        with self.assertRaises(deployment.DeploymentError):
            deployment.update_provider_scope(str(database))

    def test_changed_provider_contract_rejects_without_scope_write(self):
        for field, value in [('client_id', 'different-client'), ('enabled', 0), ('scopes', 'openid email'),
                             ('user_id_field', 'email'), ('auth_style', 1), ('slug', 'different')]:
            database = self.provider_database()
            with closing(sqlite3.connect(database)) as connection:
                connection.execute('UPDATE custom_oauth_providers SET ' + field + '=?', (value,))
                connection.commit()
            before = database.read_bytes()
            with self.assertRaises(deployment.DeploymentError):
                deployment.update_provider_scope(str(database))
            self.assertEqual(database.read_bytes(), before)

    def test_required_main_email_and_billing_policy_guards(self):
        with patch.object(deployment.base, 'validate_scope'):
            with self.assertRaises(deployment.DeploymentError):
                deployment.validate_scope({'expected_image': deployment.OLD_IMAGE, 'image': deployment.NEW_IMAGE,
                                           'version': deployment.VERSION, 'verified_main_email_claims': False})
        with self.assertRaises(deployment.DeploymentError):
            deployment.render_compose(COMPOSE.replace(b'OPENAI_STANDARD_BILLING_ENABLED: "true"',
                                                     b'OPENAI_STANDARD_BILLING_ENABLED: "false"'), deployment.OLD_IMAGE)

    def config(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = pathlib.Path(temp.name) / 'compose.yaml'
        proposed = deployment.render_compose(COMPOSE, deployment.OLD_IMAGE)
        path.write_bytes(proposed)
        return path, proposed

    def test_exact_compose_changes_preserve_chat_and_credentials_path(self):
        result = deployment.render_compose(COMPOSE, deployment.OLD_IMAGE)
        expected = COMPOSE.replace(b'image: parallellines-newapi:v0.13.2-pkce.3', b'image: "parallellines-newapi:v0.13.2-pkce.4"').replace(
            b'    volumes:', b'      MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"\n    volumes:')
        self.assertEqual(result, expected)
        doc = yaml.safe_load(result)
        self.assertEqual(doc['services']['newapi']['environment']['MAIN_OAUTH_PROFILE_SYNC_ENABLED'], 'true')
        self.assertEqual(doc['services']['openwebui'], yaml.safe_load(COMPOSE)['services']['openwebui'])

    def test_recovery_keeps_policy_on_when_disabling_relay(self):
        proposed = deployment.render_compose(COMPOSE, deployment.OLD_IMAGE)
        disabled = deployment.render_compose(proposed, deployment.NEW_IMAGE, False)
        self.assertEqual(disabled, proposed.replace(b'CHAT_OAUTH_RELAY_ENABLED: "true"', b'CHAT_OAUTH_RELAY_ENABLED: "false"'))
        self.assertIn(b'MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"', disabled)

    def test_malformed_flags_and_wrong_base_image_are_rejected(self):
        cases = [COMPOSE.replace(b'CHAT_OAUTH_RELAY_ENABLED: "true"', b'CHAT_OAUTH_RELAY_ENABLED: "garbage"'),
                 COMPOSE.replace(b'    volumes:', b'      MAIN_OAUTH_PROFILE_SYNC_ENABLED: [true]\n    volumes:'),
                 COMPOSE.replace(b'pkce.3', b'pkce.1')]
        for source in cases:
            with self.assertRaises(deployment.DeploymentError):
                deployment.render_compose(source, deployment.OLD_IMAGE)

    def test_duplicate_policy_key_is_rejected(self):
        source = COMPOSE.replace(b'    volumes:', b'      MAIN_OAUTH_PROFILE_SYNC_ENABLED: "false"\n      MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"\n    volumes:')
        with self.assertRaises(deployment.DeploymentError):
            deployment.render_compose(source, deployment.OLD_IMAGE)

    def test_only_exact_reviewed_release_pair_allowed(self):
        with patch.object(deployment.base, 'validate_scope'):
            deployment.validate_scope({'expected_image': deployment.OLD_IMAGE, 'image': deployment.NEW_IMAGE, 'version': deployment.VERSION, 'verified_main_email_claims': True})
            for old, new, version in [('parallellines-newapi:v0.13.2-pkce.1', deployment.NEW_IMAGE, deployment.VERSION),
                                      (deployment.OLD_IMAGE, 'unreviewed-image', deployment.VERSION),
                                      (deployment.OLD_IMAGE, deployment.NEW_IMAGE, 'v0.13.2-pkce.5')]:
                with self.assertRaises(deployment.DeploymentError):
                    deployment.validate_scope({'expected_image': old, 'image': new, 'version': version, 'verified_main_email_claims': True})

    def test_recovery_is_forward_only_and_never_reads_or_restores_database(self):
        path, proposed = self.config()
        calls = []
        def compose(*args):
            calls.append((args, path.read_bytes()))
        scope = {'compose': str(path), 'image': deployment.NEW_IMAGE}
        with patch.object(deployment.base, 'wait_health'), patch.object(deployment, 'verify_runtime'), \
             patch.object(deployment.sqlite3, 'connect', side_effect=AssertionError('No DB access in recovery')):
            state = deployment.recover(scope, COMPOSE, proposed, compose)
        self.assertEqual(state, 'pending_recovery_pkce4_policies_retained_relay_disabled')
        self.assertEqual(calls[0][0], ('stop', 'newapi'))
        for args, data in calls:
            if args[0] == 'up':
                self.assertIn(deployment.NEW_IMAGE.encode(), data)
                self.assertNotIn(deployment.OLD_IMAGE.encode(), data)
                self.assertIn(b'CHAT_OAUTH_RELAY_ENABLED: "false"', data)
                self.assertIn(b'MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"', data)

    def test_failed_stop_does_not_modify_config(self):
        path, proposed = self.config()
        def compose(*args):
            raise deployment.DeploymentError('stop_failed')
        state = deployment.recover({'compose': str(path)}, COMPOSE, proposed, compose)
        self.assertEqual(state, 'pending_recovery_stop_failed')
        self.assertEqual(path.read_bytes(), proposed)

    def test_concurrent_config_is_preserved(self):
        path, proposed = self.config()
        current = proposed + b'# concurrent operator change\n'
        path.write_bytes(current)
        calls = []
        state = deployment.recover({'compose': str(path)}, COMPOSE, proposed, lambda *args: calls.append(args))
        self.assertEqual(state, 'pending_recovery_concurrent_compose_change_preserved')
        self.assertEqual(calls, [('stop', 'newapi')])
        self.assertEqual(path.read_bytes(), current)

    def test_failed_new_image_start_remains_stopped_without_old_image(self):
        path, proposed = self.config()
        calls = []
        def compose(*args):
            calls.append(args)
            if args[0] == 'up':
                raise deployment.DeploymentError('start_failed')
        state = deployment.recover({'compose': str(path)}, COMPOSE, proposed, compose)
        self.assertEqual(state, 'pending_recovery_pkce4_only_operator_required')
        self.assertEqual(calls[-1], ('stop', 'newapi'))
        self.assertNotIn(deployment.OLD_IMAGE.encode(), path.read_bytes())
        self.assertIn(b'MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"', path.read_bytes())

    def test_smoke_enables_policy_without_network_accounts_or_persistent_mounts(self):
        calls = []
        def run(args):
            calls.append(args)
            if args[:2] == ['docker', 'run']:
                return 'temporary-smoke-id'
            if args[-1].endswith('/api/status'):
                return json.dumps({'success': True, 'data': {'version': deployment.VERSION, 'verified_main_email_claims': True}})
            if args[-1].endswith('/api/setup'):
                return json.dumps({'success': True, 'data': {'root_init': False}})
            return ''
        with patch.object(deployment.base, 'run', side_effect=run):
            deployment.isolated_smoke()
        self.assertIn('--network=none', calls[0])
        self.assertIn('--read-only', calls[0])
        self.assertIn('MAIN_OAUTH_PROFILE_SYNC_ENABLED=true', calls[0])
        self.assertIn('GENERATE_DEFAULT_TOKEN=false', calls[0])
        self.assertNotIn('-v', calls[0])
        self.assertEqual(calls[-1], ['docker', 'rm', '-f', 'temporary-smoke-id'])


if __name__ == '__main__':
    unittest.main()
