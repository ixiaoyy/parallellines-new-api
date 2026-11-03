"""仅检查新增 image-only 类；全部 Docker、SQLite、服务器操作为 mock。"""
import copy
import importlib.util
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

SPEC = importlib.util.spec_from_file_location('performance_release', Path(__file__).with_name('deploy-performance-release.py'))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def scope():
    return {**release.BASE.TARGET, 'utils_path': '/data/release/deploy/profile-deploy-utils.py', 'utils_sha256': 'f'*64,
            'work_dir': '/data/releases/pkce9/recovery', 'working_dir': '/opt/pl-official-candidate-20261030',
            'compose_files': [release.BASE.TARGET['compose']], 'env_files': ['/data/interpolation.env'],
            'database': release.BASE.DATA_DIRECTORY+'/new-api.db', 'status_url': 'http://127.0.0.1:13000/api/status',
            'expected_image': 'parallellines-newapi:v0.13.2-pkce.8', 'expected_image_id': 'sha256:'+'1'*64,
            'expected_binary_sha256': '2'*64, 'expected_version': 'v0.13.2-pkce.8',
            'image': 'parallellines-newapi:v0.13.2-pkce.9', 'image_id': 'sha256:'+'3'*64, 'binary_sha256': '4'*64,
            'version': 'v0.13.2-pkce.9', 'source_revision': 'a'*40,
            'new_build': {'context': '/data/releases/pkce9/image', 'dockerfile': 'Dockerfile.runtime'},
            'preserved_flags': dict.fromkeys(release.FLAGS, 'true')}


def service():
    return {'image': scope()['expected_image'], 'build': {'context': '/data/existing-image'},
            'environment': {**scope()['preserved_flags'], 'SQLITE_PATH': '/data/new-api.db', 'SENTINEL': 'preserved'},
            'env_file': ['/data/existing-secrets.env'], 'volumes': ['/data/candidates/pl-official-candidate-20261030/newapi:/data'],
            'ports': ['127.0.0.1:13000:3000'], 'mem_limit': '384m'}


class ImageOnlyReleaseTests(unittest.TestCase):
    def manager(self, value=None):
        return release.PerformanceRelease(value or scope(), utils=types.SimpleNamespace(), runner=Mock(side_effect=AssertionError('No Docker')), backup=Mock())

    def state(self, manager):
        return {'format': 1, 'scope_id': release.BASE.scope_id(manager.scope), 'phase': 'prepared', 'old_service': service(),
                'old_service_hash': 'b'*64, 'service_hash': 'b'*64, 'pending': None}

    def test_mutator_preserves_all_environment_and_gate_and_mounts(self):
        manager = self.manager()
        old = service()
        changed = manager.mutate(old)
        self.assertEqual({key: value for key, value in changed.items() if key not in {'image','build'}}, {key: value for key, value in old.items() if key not in {'image','build'}})
        self.assertEqual(changed['environment'][release.BASE.FREE_FLAG], 'true')
        self.assertEqual(old, service())
        self.assertEqual(changed['image'], scope()['image'])

    def test_missing_gate_is_not_materialized(self):
        value = scope(); value['preserved_flags'][release.BASE.FREE_FLAG] = ''
        manager = self.manager(value)
        old = service(); del old['environment'][release.BASE.FREE_FLAG]
        self.assertNotIn(release.BASE.FREE_FLAG, manager.mutate(old)['environment'])

    def test_target_version_source_and_flags_fail_closed(self):
        for key, value in [('container','other'),('expected_version','v0.13.2-pkce.7'),('version','v0.13.2-pkce.10'),('source_revision','main'),('status_url','https://api.example.invalid/api/status')]:
            candidate=scope(); candidate[key]=value
            with self.subTest(key=key), self.assertRaises(release.BASE.MaintenanceError): release.validate_scope(candidate)
        candidate=scope(); del candidate['preserved_flags'][release.BASE.FREE_FLAG]
        with self.assertRaises(release.BASE.MaintenanceError): release.validate_scope(candidate)

    def test_new_image_source_labels_are_required_but_old_image_is_compatible(self):
        manager=self.manager()
        manager.run=Mock(side_effect=[scope()['image_id'],json.dumps({'version':scope()['version'],'revision':scope()['source_revision']})])
        manager.image_available(scope()['image'],scope()['image_id'])
        self.assertEqual(manager.run.call_count,2)
        manager.run=Mock(return_value=scope()['expected_image_id'])
        manager.image_available(scope()['expected_image'],scope()['expected_image_id'])
        self.assertEqual(manager.run.call_count,1)
        manager.run=Mock(side_effect=[scope()['image_id'],json.dumps({'version':scope()['version'],'revision':'c'*40})])
        with self.assertRaisesRegex(release.BASE.MaintenanceError,'release_image_source_mismatch'): manager.image_available(scope()['image'],scope()['image_id'])

    def test_prepare_keeps_live_gate_and_captures_recovery_before_backup(self):
        manager=self.manager(); old=service()
        manager.document=Mock(return_value=('text',old,'b'*64))
        manager.compose=Mock(side_effect=lambda *args:scope()['expected_image'] if args[:2]==('config','--images') else '')
        manager.healthy=Mock();manager.verify_runtime=Mock();manager.image_available=Mock();manager.build_provenance_available=Mock()
        saved=[];result=manager.prepare(lambda state:saved.append(copy.deepcopy(state)))
        self.assertEqual([state['phase'] for state in saved],['preparing','prepared'])
        self.assertEqual(saved[0]['old_service'],old)
        manager.backup.assert_called_once_with(scope()['database'],Path(scope()['work_dir'])/'before-pkce9-new-api.db')
        self.assertEqual(manager.healthy.call_args.args[-1],'true')
        self.assertFalse(result['environment_changed']);self.assertFalse(result['database_restored'])

    def test_install_and_recovery_only_transition_images(self):
        manager=self.manager();state=self.state(manager)
        manager.compose=Mock();manager.image_available=Mock();manager.build_provenance_available=Mock()
        manager.healthy=Mock(return_value={});manager.transition=Mock()
        manager.document=Mock(return_value=('text',service(),'b'*64))
        manager.operate(state,Mock(),'install')
        replacement=manager.transition.call_args.args[3]
        self.assertEqual(replacement['environment'],service()['environment'])
        self.assertEqual(replacement['volumes'],service()['volumes'])
        manager.document=Mock(return_value=('text',replacement,'b'*64));manager.recoverable_runtime=Mock()
        manager.operate(state,Mock(),'recover')
        self.assertEqual(manager.transition.call_args.args[3],service())
        self.assertTrue(all(call.args[-1]=='true' for call in manager.healthy.call_args_list))
        with self.assertRaisesRegex(release.BASE.MaintenanceError,'unsupported_action'): manager.operate(state,Mock(),'disable')


if __name__=='__main__':
    unittest.main()
