"""免费 Chat 部署维护的纯 mock 检查；不运行 Docker、不连接 SQLite 或任何服务。"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('free_maintenance', ROOT / 'deploy-chat-free.py')
maintenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintenance)
UTIL_SPEC = importlib.util.spec_from_file_location(
    'free_maintenance_utils_test', ROOT.parent.parent / 'parallellines-chat/deploy/profile-deploy-utils.py')
utils = importlib.util.module_from_spec(UTIL_SPEC)
sys.modules[UTIL_SPEC.name] = utils
UTIL_SPEC.loader.exec_module(utils)

COMPOSE = '''# preserve other services exactly
services:
  openwebui:
    image: existing-chat
    environment: {SENTINEL: "unchanged"}
  newapi:
    image: parallellines-newapi:v0.13.2-pkce.7
    build: {context: /data/existing-image}
    env_file: [/data/existing-session.env]
    environment:
      SQLITE_PATH: /data/new-api.db
      MAIN_OAUTH_ACCOUNT_SYNC_ENABLED: "true"
      MAIN_OAUTH_PROFILE_SYNC_ENABLED: "true"
      CHAT_OAUTH_RELAY_ENABLED: "true"
      OPENAI_STANDARD_BILLING_ENABLED: "true"
      SENTINEL: "preserved"
    volumes:
      - /data/candidates/pl-official-candidate-20261030/newapi:/data
networks: {default: {}}
'''


def scope():
    return {
        **maintenance.TARGET, 'utils_path': '/data/release/deploy/profile-deploy-utils.py',
        'utils_sha256': 'f' * 64, 'work_dir': '/data/releases/free/maintenance',
        'working_dir': '/opt/pl-official-candidate-20261030',
        'compose_files': [maintenance.TARGET['compose']], 'env_files': ['/data/interpolation.env'],
        'database': maintenance.DATA_DIRECTORY + '/new-api.db',
        'status_url': 'http://127.0.0.1:13000/api/status',
        'expected_image': 'parallellines-newapi:v0.13.2-pkce.7',
        'expected_image_id': 'sha256:' + '1' * 64, 'expected_binary_sha256': '2' * 64,
        'expected_version': 'v0.13.2-pkce.7', 'image': 'parallellines-newapi:v0.13.2-pkce.8',
        'image_id': 'sha256:' + '3' * 64, 'binary_sha256': '4' * 64,
        'version': 'v0.13.2-pkce.8', 'new_build': {'context': '/data/releases/free/image'},
        'preserved_flags': dict.fromkeys(maintenance.PRESERVED_FLAGS, 'true'),
    }


class FreeMaintenanceTests(unittest.TestCase):
    def manager(self):
        return maintenance.Maintenance(scope(), utils=utils, runner=Mock(side_effect=AssertionError('No Docker')), backup=Mock())

    def state(self, manager, service=None):
        service = service or utils.load_compose(COMPOSE)['services']['newapi']
        text = utils.patch_service(COMPOSE, 'newapi', lambda target: (target.clear(), target.update(copy.deepcopy(service))))
        return {'format': 1, 'scope_id': maintenance.scope_id(manager.scope), 'phase': 'prepared',
                'old_service': utils.load_compose(COMPOSE)['services']['newapi'], 'old_gate': '',
                'service_hash': utils.service_hash(text, 'newapi'), 'pending': None, 'ever_enabled': False}, text

    def test_install_and_gate_mutators_only_change_approved_values(self):
        manager = self.manager()
        original = utils.load_compose(COMPOSE)['services']['newapi']
        changed = manager.mutate(original, 'install')
        expected = copy.deepcopy(original)
        expected['image'] = scope()['image']
        expected['build'] = scope()['new_build']
        expected['environment'][maintenance.FREE_FLAG] = 'false'
        self.assertEqual(changed, expected)
        rendered = utils.patch_service(COMPOSE, 'newapi', lambda target: (target.clear(), target.update(changed)))
        self.assertEqual(rendered[:rendered.index('  newapi:')], COMPOSE[:COMPOSE.index('  newapi:')])
        self.assertEqual(rendered[rendered.index('networks:'):], COMPOSE[COMPOSE.index('networks:'):])
        enabled = manager.mutate(changed, 'enable')
        disabled = manager.mutate(enabled, 'disable')
        self.assertEqual(disabled, changed)
        self.assertEqual(enabled['environment'], {**changed['environment'], maintenance.FREE_FLAG: 'true'})
        self.assertEqual(original, utils.load_compose(COMPOSE)['services']['newapi'])

    def test_wrong_target_version_database_and_status_fail_before_commands(self):
        for key, value in [('service', 'openwebui'), ('expected_version', 'v0.13.2-pkce.6'),
                           ('database', '/data/another/new-api.db'), ('status_url', 'https://other.invalid/api/status'),
                           ('utils_path', '/tmp/helper.py')]:
            invalid = scope(); invalid[key] = value
            runner = Mock()
            with self.subTest(key=key), self.assertRaises(maintenance.MaintenanceError):
                maintenance.Maintenance(invalid, utils=utils, runner=runner)
            runner.assert_not_called()

    def test_database_mount_is_verified_without_reading_database(self):
        service = utils.load_compose(COMPOSE)['services']['newapi']
        metadata = {'mounts': [{'Type': 'bind', 'Destination': '/data', 'Source': maintenance.DATA_DIRECTORY}]}
        maintenance.verify_binding(service, metadata, scope()['database'], {'SQLITE_PATH': '/data/new-api.db'})
        for wrong in [{'Type': 'volume', 'Destination': '/data', 'Source': maintenance.DATA_DIRECTORY},
                      {'Type': 'bind', 'Destination': '/data', 'Source': '/data/other'}]:
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.verify_binding(service, {'mounts': [wrong]}, scope()['database'], {'SQLITE_PATH': '/data/new-api.db'})

    def test_scope_and_concurrent_service_hash_refuse_any_write(self):
        manager = self.manager(); state, text = self.state(manager)
        manager.document = Mock(return_value=(text, state['old_service'], '0' * 64))
        save = Mock()
        with self.assertRaisesRegex(maintenance.MaintenanceError, 'target_service_changed_concurrently'):
            manager.transition(state, save, 'install', manager.mutate(state['old_service'], 'install'))
        save.assert_not_called(); manager.run.assert_not_called()
        invalid = copy.deepcopy(state); invalid['scope_id'] = 'not-this-scope'
        with self.assertRaisesRegex(maintenance.MaintenanceError, 'state_scope_changed'):
            manager.state_matches(invalid, state['service_hash'])

    def test_prepare_saves_recovery_point_then_readonly_backup_before_ready(self):
        manager = self.manager()
        service = utils.load_compose(COMPOSE)['services']['newapi']
        old_hash = utils.service_hash(COMPOSE, 'newapi')
        manager.document = Mock(return_value=(COMPOSE, service, old_hash))
        manager.compose = Mock(side_effect=lambda *args: scope()['expected_image'] if args[:2] == ('config', '--images') else '')
        manager.healthy = Mock(); manager.verify_runtime = Mock(); manager.image_available = Mock()
        manager.build_provenance_available = Mock()
        saved = []
        result = manager.prepare(lambda value: saved.append(copy.deepcopy(value)))
        self.assertEqual([value['phase'] for value in saved], ['preparing', 'prepared'])
        self.assertEqual(saved[0]['old_service'], service)
        manager.backup.assert_called_once_with(scope()['database'], Path(scope()['work_dir']) / 'before-pkce8-new-api.db')
        self.assertEqual(result['phase'], 'prepared')
        self.assertFalse(result['database_restored'])

    def test_transition_passes_exact_cas_and_no_build_or_pull(self):
        manager = self.manager(); state, text = self.state(manager)
        manager.document = Mock(return_value=(text, state['old_service'], state['service_hash']))
        intended_service = manager.mutate(state['old_service'], 'install')
        after = utils.patch_service(text, 'newapi', lambda target: (target.clear(), target.update(intended_service)))
        cas = Mock(return_value={'after_service_sha256': utils.service_hash(after, 'newapi')})
        manager.utils = types.SimpleNamespace(patch_service=utils.patch_service, service_hash=utils.service_hash, cas_service_update=cas)
        manager.compose = Mock(side_effect=lambda *args: scope()['image'] if args[:2] == ('config', '--images') else '')
        save = Mock()
        before_hash = state['service_hash']
        manager.transition(state, save, 'install', intended_service)
        self.assertEqual(cas.call_args.args[:3], (Path(scope()['compose']), 'newapi', before_hash))
        target = copy.deepcopy(state['old_service']); cas.call_args.args[3](target)
        self.assertEqual(target, intended_service)
        self.assertEqual(manager.compose.call_args_list[-1].args,
                         ('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'newapi'))
        self.assertEqual(save.call_count, 2)

    def test_failed_cas_is_explicit_pending_and_never_restarts(self):
        manager = self.manager(); state, text = self.state(manager)
        manager.document = Mock(return_value=(text, state['old_service'], state['service_hash']))
        manager.utils = types.SimpleNamespace(patch_service=utils.patch_service, service_hash=utils.service_hash,
                                             cas_service_update=Mock(side_effect=RuntimeError('synthetic CAS rejection')))
        manager.compose = Mock(); saves = []
        with self.assertRaises(RuntimeError):
            manager.transition(state, lambda value: saves.append(copy.deepcopy(value)), 'install', manager.mutate(state['old_service'], 'install'))
        self.assertTrue(manager.partial)
        self.assertEqual(saves[-1]['phase'], 'install_pending')
        self.assertEqual(set(saves[-1]['pending']), {'before_hash', 'after_hash'})
        manager.compose.assert_not_called()

    def test_enable_records_possible_exposure_before_activation(self):
        manager = self.manager()
        candidate = manager.mutate(utils.load_compose(COMPOSE)['services']['newapi'], 'install')
        state, text = self.state(manager, candidate); state['phase'] = 'installed'
        manager.document = Mock(return_value=(text, candidate, state['service_hash']))
        manager.compose = Mock(); manager.healthy = Mock(return_value={}); manager.image_available = Mock()
        def stopped_transition(value, save, action, replacement):
            self.assertTrue(value['ever_enabled'])
            raise maintenance.MaintenanceError('synthetic_activation_stop')
        manager.transition = stopped_transition
        with self.assertRaises(maintenance.MaintenanceError): manager.operate(state, Mock(), 'enable')

    def test_recovery_requires_closed_gate_and_drain_then_uses_only_this_old_service(self):
        manager = self.manager()
        candidate = manager.mutate(utils.load_compose(COMPOSE)['services']['newapi'], 'install')
        state, text = self.state(manager, candidate)
        state.update(phase='disabled', ever_enabled=True, drain_after=1100)
        manager.document = Mock(return_value=(text, candidate, state['service_hash']))
        manager.compose = Mock(); manager.healthy = Mock(return_value={}); manager.image_available = Mock()
        manager.transition = Mock(); manager.recoverable_runtime = Mock(return_value={'image_id': scope()['image_id'], 'running': False})
        with patch.object(maintenance.time, 'time', return_value=1000), self.assertRaisesRegex(maintenance.MaintenanceError, 'drain'):
            manager.operate(state, Mock(), 'recover')
        manager.transition.assert_not_called()
        with patch.object(maintenance.time, 'time', return_value=1200), \
             patch.object(maintenance.sqlite3, 'connect', side_effect=AssertionError('No DB restore')):
            manager.operate(state, Mock(), 'recover')
        self.assertEqual(manager.transition.call_args.args[2], 'recover')
        self.assertEqual(manager.transition.call_args.args[3], state['old_service'])
        self.assertEqual(state['phase'], 'recovered')
        enabled = manager.mutate(candidate, 'enable')
        state, text = self.state(manager, enabled)
        manager.document = Mock(return_value=(text, enabled, state['service_hash']))
        with self.assertRaisesRegex(maintenance.MaintenanceError, 'disable_free_gate'):
            manager.operate(state, Mock(), 'recover')

    def test_existing_closed_gate_is_verified_without_restart(self):
        manager = self.manager()
        candidate = manager.mutate(utils.load_compose(COMPOSE)['services']['newapi'], 'install')
        state, text = self.state(manager, candidate); state['phase'] = 'disabled'
        manager.document = Mock(return_value=(text, candidate, state['service_hash']))
        manager.compose = Mock(); manager.healthy = Mock(return_value={}); manager.transition = Mock()
        result = manager.operate(state, Mock(), 'disable')
        self.assertTrue(result['no_change']); manager.transition.assert_not_called()

    def test_cli_never_exposes_unexpected_error_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'scope.json'); path.write_text(json.dumps(scope()), encoding='utf-8')
            output = io.StringIO()
            with patch.object(sys, 'argv', ['deploy-chat-free.py', str(path), 'health']), \
                 patch.object(maintenance, 'Maintenance', side_effect=RuntimeError('synthetic-secret-value')), \
                 patch('sys.stdout', output):
                self.assertEqual(maintenance.main(), 1)
            self.assertNotIn('synthetic-secret-value', output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['reason'], 'maintenance_stopped')


if __name__ == '__main__':
    unittest.main()
