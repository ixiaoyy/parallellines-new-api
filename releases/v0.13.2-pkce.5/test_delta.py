import base64
import copy
import hashlib
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('delta', pathlib.Path(__file__).with_name('apply-delta.py'))
delta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta)


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.base = b'abcd'
        self.target = b'abce'
        for key, value in {'BASE_SHA': hashlib.sha256(self.base).hexdigest(),
                           'TARGET_SHA': hashlib.sha256(self.target).hexdigest(),
                           'BASE_SIZE': 4, 'TARGET_SIZE': 4}.items():
            handle = patch.object(delta, key, value)
            handle.start()
            self.addCleanup(handle.stop)
        self.document = {'format': 'pl-bytecopy-xor-v1', 'base_sha256': delta.BASE_SHA,
                         'target_sha256': delta.TARGET_SHA, 'base_size': 4, 'target_size': 4,
                         'ops': [['c', 0, 3], ['x', 3, base64.b64encode(b'\x01').decode()]]}

    def test_exact_reconstruction(self):
        self.assertEqual(delta.reconstruct(self.base, self.document), self.target)

    def test_wrong_base_refused(self):
        with self.assertRaisesRegex(ValueError, 'base_sha'):
            delta.reconstruct(b'abcf', self.document)

    def test_wrong_contract_refused(self):
        self.document['target_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'contract'):
            delta.reconstruct(self.base, self.document)

    def test_bounds_and_unknown_operations_refused(self):
        for operation in [['c', -1, 4], ['c', 0, 5], ['c', True, 3], ['x', 4, 'AQ=='],
                          ['x', -1, 'AQ=='], ['x', True, 'AQ=='], ['z', 0, 4], ['i', 'bad*']]:
            document = copy.deepcopy(self.document)
            document['ops'] = [operation]
            with self.assertRaises((ValueError, TypeError)):
                delta.reconstruct(self.base, document)

    def test_output_overflow_refused(self):
        self.document['ops'] = [['c', 0, 4], ['i', 'AQ==']]
        with self.assertRaises(ValueError):
            delta.reconstruct(self.base, self.document)

    def test_final_hash_refused(self):
        self.document['ops'] = [['c', 0, 4]]
        with self.assertRaisesRegex(ValueError, 'target_sha'):
            delta.reconstruct(self.base, self.document)


if __name__ == '__main__':
    unittest.main()
