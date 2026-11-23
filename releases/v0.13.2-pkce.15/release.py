"""从已冻结的 pkce.14 基线准备并离线构建配置驱动多角色网关，零前端改动、不接触业务系统。"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


RELEASE = Path(__file__).resolve().parent
REPO = RELEASE.parents[1]
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('pkce14_recipe', RELEASE.parent / 'v0.13.2-pkce.14/release.py')
PKCE14 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PKCE14)
PKCE10, BASE = PKCE14.PKCE10, PKCE14.BASE


def settings():
    """只接受冻结的 pkce.14 完整基线与本版配置驱动 Go 增量。"""
    lock = BASE.read_json(RELEASE / 'upstream.lock.json')
    for key in ('base_release_lock', 'base_source_manifest', 'source_manifest', 'frontend_manifest'):
        if BASE.digest(REPO / lock[key]) != lock[key + '_sha256']:
            raise RuntimeError('release_manifest_changed: ' + key)
    for patch in lock['patches']:
        if BASE.digest(REPO / patch['file']) != patch['sha256']:
            raise RuntimeError('release_patch_changed: ' + patch['file'])
    return lock


def verify(source):
    """核对完整公开源码与复用的 pkce.14 冻结前端产物。"""
    lock = settings()
    if PKCE10.file_set(source) != BASE.read_json(REPO / lock['source_manifest'])['files']:
        raise RuntimeError('tavern_config_roles_source_changed')
    PKCE10.PREVIOUS.public_assets(source / 'web/dist', lock)
    if BASE.web_identity(source / 'web') != lock['frontend_source_identity']:
        raise RuntimeError('flux_frontend_source_identity_changed')
    return lock


def prepare(base, destination):
    """复制已验证的 pkce.14 完整基线（含冻结 web/dist）到全新目录并应用本版 Go 增量。"""
    lock = settings()
    expected = BASE.read_json(REPO / lock['base_source_manifest'])['files']
    PKCE14.verify(base)
    if destination.exists():
        raise RuntimeError('flux_candidate_destination_exists')
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / 'source'
    for name in expected:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / name, target)
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(destination.resolve())}
    for entry in lock['patches']:
        patch = str(REPO / entry['file'])
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', '--check', patch], cwd=source, env=env, check=True, timeout=30)
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', patch], cwd=source, env=env, check=True, timeout=30)
    verify(source)
    return source


def build(source, cache, output):
    """离线交叉编译候选，用实际 ELF 的 embed 表核对所有前端资源。"""
    lock = verify(source)
    if output.exists():
        raise RuntimeError('output_already_exists')
    env = BASE.cache_environment(cache)
    go = shutil.which('go')
    if not go or subprocess.check_output([go, 'env', 'GOVERSION'], env=env, text=True, timeout=30).strip() != 'go1.26.1':
        raise RuntimeError('existing_go_1_26_1_required')
    env.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOEXPERIMENT='greenteagc', GOSUMDB='off')
    output.mkdir(parents=True)
    binary = output / 'new-api-linux-amd64'
    start = time.monotonic()
    subprocess.run([go, 'build', '-mod=readonly', '-buildvcs=false', '-ldflags',
                    '-s -w -X github.com/QuantumNous/new-api/common.Version=' + lock['application_version'],
                    '-o', str(binary), '.'], cwd=source, env=env, check=True, timeout=1800)
    embedded = PKCE10.PREVIOUS.binary_assets(binary, lock)
    receipt = {'application_version': lock['application_version'], 'published': False, 'go_build_run': True,
               'go_seconds': round(time.monotonic() - start, 3),
               'release_lock_sha256': BASE.digest(RELEASE / 'upstream.lock.json'),
               'frontend_manifest_sha256': lock['frontend_manifest_sha256'],
               'binary_sha256': embedded['binary_sha256'], 'verified_public_files': embedded['verified_public_files']}
    BASE.write_json(output / 'build-receipt.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--base-source', type=Path, required=True)
    prep.add_argument('--destination', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--source', type=Path, required=True)
    compile_cmd = commands.add_parser('build')
    compile_cmd.add_argument('--source', type=Path, required=True)
    compile_cmd.add_argument('--cache-dir', type=Path, required=True)
    compile_cmd.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.base_source.resolve(), args.destination.resolve()))
    elif args.command == 'verify':
        lock = verify(args.source.resolve())
        print(json.dumps({'prepared_candidate': lock['application_version'], 'production_ready': lock['production_ready'], 'verified': True}))
    elif args.command == 'build':
        print(json.dumps(build(args.source.resolve(), args.cache_dir.resolve(), args.output_dir.resolve()), indent=2))
