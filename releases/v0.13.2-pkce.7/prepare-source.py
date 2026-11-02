"""从固定 pkce.6 源码归档准备统一账号同步版本；不联网、不编译、不连接服务。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

RELEASE = Path(__file__).resolve().parent
REPO = RELEASE.parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(base_archive, destination, with_tests=False):
    """验证固定基线并写入全新目录；with_tests 追加不访问真实服务的验证补丁。"""
    lock = json.loads((RELEASE / 'upstream.lock.json').read_text(encoding='utf-8'))
    manifest = json.loads((REPO / 'patches/account-sync-manifest.json').read_text(encoding='utf-8'))
    if digest(base_archive) != lock['base_source_archive_sha256'] or destination.exists():
        raise RuntimeError('base_archive_mismatch_or_destination_exists')
    patches = [lock['patches'][-1]]
    if with_tests:
        patches.append(lock['verification_patch'])
    for entry in patches:
        if digest(REPO / entry['file']) != entry['sha256']:
            raise RuntimeError('release_patch_mismatch')
    source = destination / 'source'
    with tarfile.open(base_archive) as archive:
        for member in archive:
            if not member.name.startswith('source/') or member.isdir():
                continue
            target = destination / member.name
            if not member.isfile() or not target.resolve().is_relative_to(source.resolve()):
                raise RuntimeError('unsafe_source_archive_entry')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    for entry in manifest['files']:
        path = source / entry['path']
        if entry['base_sha256'] is None:
            if path.exists():
                raise RuntimeError('unexpected_base_file')
        elif digest(path) != entry['base_sha256']:
            raise RuntimeError('base_file_mismatch: ' + entry['path'])
    # 阻止 Git 向上发现部署仓库，使相对补丁只作用于本次全新源码目录。
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(destination.resolve())}
    for entry in patches:
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', '--check', str(REPO / entry['file'])], cwd=source, env=env, check=True)
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', str(REPO / entry['file'])], cwd=source, env=env, check=True)
    for entry in manifest['files']:
        if digest(source / entry['path']) != entry['result_sha256']:
            raise RuntimeError('result_file_mismatch: ' + entry['path'])
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-archive', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--with-tests', action='store_true')
    args = parser.parse_args()
    print(prepare(args.base_archive.resolve(), args.destination.resolve(), args.with_tests))
