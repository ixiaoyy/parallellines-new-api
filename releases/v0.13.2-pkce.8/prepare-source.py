"""从固定 pkce.6 归档依次准备 pkce.7 和本版免费 Chat 增量；不联网、不编译、不连接服务。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

RELEASE = Path(__file__).resolve().parent
REPO = RELEASE.parent.parent


def digest(path):
    """返回已固定发布输入的 SHA-256，供归档与补丁完整性核对。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(base_archive, destination, with_tests=False):
    """复用前版准备器并返回 source 目录；核对前后清单，仅写入全新目标，不联网或执行 Go。"""
    lock = json.loads((RELEASE / 'upstream.lock.json').read_text(encoding='utf-8'))
    manifest = json.loads((REPO / 'patches/free-chat-manifest.json').read_text(encoding='utf-8'))
    previous_lock = REPO / lock['base_release_lock']
    if destination.exists() or digest(base_archive) != lock['base_source_archive_sha256']:
        raise RuntimeError('base_archive_mismatch_or_destination_exists')
    if digest(previous_lock) != lock['base_release_lock_sha256']:
        raise RuntimeError('base_release_lock_mismatch')
    production = lock['patches'][-1]
    patches = [production]
    if with_tests:
        patches.append(lock['verification_patch'])
    for entry in patches:
        if digest(REPO / entry['file']) != entry['sha256']:
            raise RuntimeError('release_patch_mismatch')
    spec = importlib.util.spec_from_file_location('pkce7_prepare', previous_lock.with_name('prepare-source.py'))
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    source = previous.prepare(base_archive, destination, with_tests)
    for entry in manifest['files']:
        path = source / entry['path']
        if entry['base_sha256'] is None:
            if path.exists():
                raise RuntimeError('unexpected_base_file: ' + entry['path'])
        elif not path.is_file() or digest(path) != entry['base_sha256']:
            raise RuntimeError('base_file_mismatch: ' + entry['path'])
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
