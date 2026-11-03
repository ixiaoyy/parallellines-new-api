"""本地配方的离线合同检查，不安装/执行 Bun、Go，不访问服务。"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('local_build', REPO / 'scripts/build-performance-local.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class LocalBuildTests(unittest.TestCase):
    def test_invalid_archive_and_existing_target_rejected_before_extract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'bad.tar.gz'
            archive.write_bytes(b'not the fixed archive')
            with self.assertRaisesRegex(RuntimeError, 'base_archive_mismatch'):
                BUILD.prepare(archive, root / 'source-output')
            self.assertFalse((root / 'source-output').exists())

    def test_web_identity_excludes_build_outputs_but_includes_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            web = Path(directory)
            (web / 'bun.lock').write_text('locked')
            original = BUILD.web_identity(web)
            (web / 'dist').mkdir()
            (web / 'dist/index.html').write_text('built')
            self.assertEqual(original, BUILD.web_identity(web))
            (web / 'bun.lock').write_text('changed')
            self.assertNotEqual(original, BUILD.web_identity(web))

    def test_existing_go_caches_are_reused_and_no_toolchain_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = {'GOCACHE': str(root / 'existing-build'), 'GOMODCACHE': str(root / 'existing-modules')}
            with patch.dict(os.environ, existing), patch.object(shutil, 'which', return_value='go'), patch.object(BUILD.subprocess, 'check_output', return_value=json.dumps(existing)):
                env = BUILD.cache_environment(root / 'new-release-cache')
            self.assertEqual(env['GOCACHE'], existing['GOCACHE'])
            self.assertEqual(env['GOMODCACHE'], existing['GOMODCACHE'])
            self.assertEqual(env['GOTOOLCHAIN'], 'local')
            self.assertEqual(env['GOPROXY'], 'off')

    def test_frontend_cache_hit_replaces_old_assets_without_compiling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            web = source / 'web'
            web.mkdir(parents=True)
            (web / 'bun.lock').write_text('locked')
            (web / 'dist').mkdir()
            (web / 'dist/obsolete.js').write_text('old asset')
            cache = root / 'cache'
            cached = cache / 'frontend' / BUILD.web_identity(web)
            (cached / 'dist/assets').mkdir(parents=True)
            (cached / 'dist/index.html').write_text('<script type="module" src="/assets/main-12345678.js"></script>')
            (cached / 'dist/assets/main-12345678.js').write_text('console.log("built");')
            BUILD.write_json(cached / 'files.json', BUILD.file_manifest(cached / 'dist'))
            with patch.object(BUILD, 'verify_source'), patch.object(BUILD, 'cache_environment', return_value={'GOCACHE': 'existing', 'GOMODCACHE': 'existing'}), patch.object(BUILD, 'run') as runner:
                receipt = BUILD.build(source, cache, root / 'output', frontend_only=True)
            runner.assert_not_called()
            self.assertTrue(receipt['frontend_cache_hit'])
            self.assertFalse(receipt['published'])
            self.assertFalse((web / 'dist/obsolete.js').exists())
            self.assertEqual(receipt['frontend']['bytes'], 21)

    def test_only_successful_fingerprinted_static_assets_have_long_cache(self):
        config = (REPO / 'deploy/nginx-api.conf').read_text(encoding='utf-8')
        expression = re.search(r'"(~\^200:/assets/[^\"]+)"', config).group(1)[1:]
        for status, path, expected in [(200, '/assets/index-CAbcEbNk.js', True), (200, '/assets/index.css', False), (404, '/assets/index-CAbcEbNk.js', False), (200, '/oauth-relay/v1/models', False), (200, '/api/user/self', False), (200, '/api/user/topup', False), (200, '/oauth-relay/v1/chat/completions', False), (200, '/login', False), (200, '/', False)]:
            self.assertEqual(bool(re.match(expression, f'{status}:{path}')), expected, path)
        self.assertIn('default "no-store";', config)
        self.assertIn('proxy_cache off;', config)
        self.assertIn('add_header Cache-Control $pl_api_cache_control always;', config)


if __name__ == '__main__':
    unittest.main()
