"""承接本地前端性能配方的 OAuth relay 耗时增量；不安装、不发布或调用真实业务。"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / 'patches/relay-timing-performance-manifest.json'
SPEC = importlib.util.spec_from_file_location('frontend_performance_build', REPO / 'scripts/build-performance-local.py')
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)


def check_files(source, entries, key):
    """核对本次声明的生产/验证文件身份；未声明的新业务变更不能混入交付。"""
    for entry in entries:
        path = source / entry['path']
        expected = entry[key]
        if (expected is None and path.exists()) or (expected is not None and (not path.is_file() or BASE.digest(path) != expected)):
            raise RuntimeError('timing_source_mismatch: ' + entry['path'])


def manifest():
    """固定上一批前端配方身份，不改变任何已发布 release 锁或前端构建输入。"""
    value = BASE.read_json(MANIFEST)
    if BASE.digest(REPO / value['base_frontend_manifest']) != value['base_frontend_manifest_sha256']:
        raise RuntimeError('frontend_performance_baseline_changed')
    return value


def verify(source, with_tests=False):
    """核对前端、耗时增量及原 frt/身份/计费/超时/启动合同未变。"""
    value = manifest()
    BASE.verify_source(source)
    check_files(source, value['files'], 'result_sha256')
    check_files(source, [{'path': path, 'sha256': digest} for path, digest in value['preserved_files'].items()], 'sha256')
    if with_tests:
        check_files(source, value['verification_files'], 'result_sha256')
    return value


def prepare(archive, destination, with_tests=False):
    """准备新目录并顺序应用前端、耗时、可选验证补丁；不覆盖前两批的有效产物。"""
    value = manifest()
    patches = [value['production_patch']]
    if with_tests:
        patches.append(value['verification_patch'])
    for patch in patches:
        if BASE.digest(REPO / patch['file']) != patch['sha256']:
            raise RuntimeError('timing_patch_mismatch')
    source = BASE.prepare(archive, destination)
    check_files(source, value['files'], 'base_sha256')
    env = dict(os.environ)
    env['GIT_CEILING_DIRECTORIES'] = str(destination)
    for patch in patches:
        BASE.run(['git', '-c', 'core.autocrlf=false', 'apply', '--check', str(REPO / patch['file'])], source, env)
        BASE.run(['git', '-c', 'core.autocrlf=false', 'apply', str(REPO / patch['file'])], source, env)
    verify(source, with_tests)
    BASE.write_json(destination / 'relay-timing-source.json', {'published': False, 'application_version': value['application_version'], 'production_patch_sha256': value['production_patch']['sha256'], 'verification_applied': with_tests})
    return source


def test(source, cache, output):
    """执行受影响包的离线合成请求/计费拒绝用例；不运行服务或真实 OAuth/模型流量。"""
    verify(source, with_tests=True)
    env = BASE.cache_environment(cache)
    env.update(CGO_ENABLED='0', GOEXPERIMENT='greenteagc', GOFLAGS='-mod=readonly')
    env.pop('GOOS', None)
    env.pop('GOARCH', None)
    go = shutil.which('go')
    if not go or subprocess.check_output([go, 'env', 'GOVERSION'], env=env, text=True, timeout=30).strip() != 'go1.26.1':
        raise RuntimeError('existing_go_1_26_1_required')
    command = [go, 'test', './common', './middleware', './relay/channel', './service', './router', '-run', '^(TestOAuthRelayTiming|TestChatOAuthRelayIntegration$|TestChatFreeNativeRelayIntegration$)', '-count=1', '-timeout=120s']
    started = time.monotonic()
    result = subprocess.run(command, cwd=source, env=env, text=True, capture_output=True, timeout=1800)
    receipt = {'published': False, 'toolchain': 'go1.26.1', 'real_oauth_model_or_database_calls': False, 'command': command[1:], 'seconds': round(time.monotonic() - started, 3), 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    BASE.write_json(output, receipt)
    print(result.stdout, end='')
    print(result.stderr, end='')
    if result.returncode:
        raise RuntimeError('isolated_timing_tests_failed; see ' + str(output))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--base-archive', type=Path, required=True)
    preparation.add_argument('--destination', type=Path, required=True)
    preparation.add_argument('--with-tests', action='store_true')
    for name in ('test', 'build'):
        command = commands.add_parser(name)
        command.add_argument('--source', type=Path, required=True)
        command.add_argument('--cache-dir', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.base_archive.resolve(), args.destination.resolve(), args.with_tests))
    elif args.command == 'test':
        test(args.source.resolve(), args.cache_dir.resolve(), args.output.resolve())
    else:
        value = verify(args.source.resolve())
        print(json.dumps(BASE.build(args.source.resolve(), args.cache_dir.resolve(), args.output.resolve(), application_version=value['application_version']), ensure_ascii=False, indent=2))
