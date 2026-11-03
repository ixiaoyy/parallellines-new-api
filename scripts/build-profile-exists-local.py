"""在既有前端/耗时观测上追加单行存在性查询；只做本地准备、合成验证与构建。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / 'patches/profile-collision-exists-manifest.json'
SPEC = importlib.util.spec_from_file_location('relay_timing_build', REPO / 'scripts/build-relay-timing-local.py')
TIMING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIMING)
BASE = TIMING.BASE
ACCOUNT_FILE = 'oauth/main_account.go'


def manifest():
    """只允许明确批准的碰撞查询文件覆盖上一批的同文件不变断言，不放宽其他合同。"""
    value = BASE.read_json(MANIFEST)
    if BASE.digest(REPO / value['base_timing_manifest']) != value['base_timing_manifest_sha256']:
        raise RuntimeError('relay_timing_baseline_changed')
    previous = TIMING.manifest()
    if len(value['files']) != 1 or value['files'][0]['path'] != ACCOUNT_FILE or value['files'][0]['base_sha256'] != previous['preserved_files'][ACCOUNT_FILE]:
        raise RuntimeError('only_the_approved_collision_query_may_change')
    return value, previous


def verify(source, with_tests=False):
    """保留前端、耗时和其余原合同；碰撞函数外的账号锁/事务/角色/Redis 恢复代码须逐字相同。"""
    value, previous = manifest()
    BASE.verify_source(source)
    TIMING.check_files(source, previous['files'], 'result_sha256')
    preserved = [{'path': path, 'sha256': digest} for path, digest in previous['preserved_files'].items() if path != ACCOUNT_FILE]
    TIMING.check_files(source, preserved, 'sha256')
    TIMING.check_files(source, value['files'], 'result_sha256')
    text = (source / ACCOUNT_FILE).read_text(encoding='utf-8')
    sections = value['preserved_main_account_sections']
    if hashlib.sha256(text[:text.index(sections['prefix_marker'])].encode()).hexdigest() != sections['prefix_sha256'] or hashlib.sha256(text[text.index(sections['tail_marker']):].encode()).hexdigest() != sections['tail_sha256']:
        raise RuntimeError('account_code_outside_collision_query_changed')
    if with_tests:
        TIMING.check_files(source, previous['verification_files'], 'result_sha256')
        TIMING.check_files(source, value['verification_files'], 'result_sha256')
    return value


def prepare(archive, destination, with_tests=False):
    """顺序应用已核验前端、耗时和查询补丁，目标必须全新；不修改历史归档/发布锁。"""
    value, _ = manifest()
    patches = [value['production_patch']]
    if with_tests:
        patches.append(value['verification_patch'])
    for patch in patches:
        if BASE.digest(REPO / patch['file']) != patch['sha256']:
            raise RuntimeError('profile_exists_patch_mismatch')
    source = TIMING.prepare(archive, destination, with_tests)
    TIMING.check_files(source, value['files'], 'base_sha256')
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(destination)}
    for patch in patches:
        BASE.run(['git', '-c', 'core.autocrlf=false', 'apply', '--check', str(REPO / patch['file'])], source, env)
        BASE.run(['git', '-c', 'core.autocrlf=false', 'apply', str(REPO / patch['file'])], source, env)
    verify(source, with_tests)
    BASE.write_json(destination / 'profile-exists-source.json', {'published': False, 'application_version': value['application_version'], 'production_patch_sha256': value['production_patch']['sha256'], 'verification_applied': with_tests})
    return source


def validate(source, cache, output, comparison=False):
    """正确性只运行定向用例；比较固定 6000 行、32 对交错批次(每批64次)、45 秒内，不访问业务服务。"""
    verify(source, with_tests=True)
    env = BASE.cache_environment(cache)
    env.update(CGO_ENABLED='0', GOEXPERIMENT='greenteagc', GOFLAGS='-mod=readonly')
    env.pop('GOOS', None)
    env.pop('GOARCH', None)
    go = shutil.which('go')
    if not go or subprocess.check_output([go, 'env', 'GOVERSION'], env=env, text=True, timeout=30).strip() != 'go1.26.1':
        raise RuntimeError('existing_go_1_26_1_required')
    if comparison:
        packages = ['./oauth']
        pattern = '^TestMainProfileCollisionExistsBoundedComparison$'
    else:
        packages = ['./oauth', './controller']
        pattern = '^(TestMainProfileCollisionExists(MatchesCount|DatabaseError|SQLAndQueryCount)$|TestMainProfileExists|TestMainProfileUpdatesOnlyBoundIdentityAndProfile$|TestMainProfileCollisionRollsBackWithoutMergeIncludingDeletedUsers$|TestMainProfileNewRegistrationNoAliasAndNoMerge$|TestMainProfileDisabledDeletedUnverifiedAndProviderChangedFailClosed$|TestMainAccount)'
    command = [go, 'test', *packages, '-run', pattern, '-v', '-count=1', '-timeout=60s']
    started = time.monotonic()
    result = subprocess.run(command, cwd=source, env=env, text=True, encoding='utf-8', capture_output=True, timeout=180)
    receipt = {'published': False, 'business_system_calls': False, 'fixtures': 'synthetic SQLite and in-process RESP; MySQL/PostgreSQL SQL generation uses DryRun and no automatic ping', 'comparison': comparison, 'command': command[1:], 'seconds': round(time.monotonic()-started, 3), 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    if comparison and result.returncode == 0:
        marker = 'PROFILE_COLLISION_COMPARISON '
        reports = [json.loads(line.split(marker, 1)[1]) for line in result.stdout.splitlines() if marker in line]
        if len(reports) != 1:
            raise RuntimeError('bounded_comparison_report_missing')
        receipt['query_comparison'] = reports[0]
    BASE.write_json(output, receipt)
    print(result.stdout, end='')
    print(result.stderr, end='')
    if result.returncode:
        raise RuntimeError('profile_exists_validation_failed; see ' + str(output))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--base-archive', type=Path, required=True)
    preparation.add_argument('--destination', type=Path, required=True)
    preparation.add_argument('--with-tests', action='store_true')
    for name in ('check', 'compare', 'build'):
        command = commands.add_parser(name)
        command.add_argument('--source', type=Path, required=True)
        command.add_argument('--cache-dir', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.base_archive.resolve(), args.destination.resolve(), args.with_tests))
    elif args.command in {'check', 'compare'}:
        validate(args.source.resolve(), args.cache_dir.resolve(), args.output.resolve(), args.command == 'compare')
    else:
        value = verify(args.source.resolve())
        print(json.dumps(BASE.build(args.source.resolve(), args.cache_dir.resolve(), args.output.resolve(), application_version=value['application_version']), ensure_ascii=False, indent=2))
