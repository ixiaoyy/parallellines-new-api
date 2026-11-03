"""pkce.9 固定对应源码/公开前端/版本打包；不安装、不推送、不上传、不部署。"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import tarfile

RELEASE = Path(__file__).resolve().parent
REPO = RELEASE.parent.parent
SPEC = importlib.util.spec_from_file_location('profile_exists_build', REPO / 'scripts/build-profile-exists-local.py')
LOCAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOCAL)
BASE = LOCAL.BASE


def settings():
    """只接受本版已固定的生产、验证、前端及完整展开源码清单。"""
    lock = BASE.read_json(RELEASE / 'upstream.lock.json')
    for key in ('profile_manifest', 'frontend_manifest', 'source_manifest'):
        if BASE.digest(REPO / lock[key]) != lock[key + '_sha256']:
            raise RuntimeError('release_manifest_changed: ' + key)
    return lock


def public_assets(directory, lock):
    """all: 嵌入前拒绝私密文件名、map、链接及任何不在公开清单中的额外文件。"""
    manifest = BASE.read_json(REPO / lock['frontend_manifest'])
    actual = {}
    allowed = {'.png', '.webp', '.ico', '.html', '.txt', '.js', '.css', '.woff2', '.woff', '.ttf'}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('frontend_symlink_not_allowed')
        relative = path.relative_to(directory)
        if any(part.startswith('.') or re.search(r'(^|[._-])(env|secrets?|private|credentials?|backup|runtime)([._-]|$)', part, re.I) for part in relative.parts):
            raise RuntimeError('non_public_frontend_name: ' + relative.as_posix())
        if path.is_file():
            if path.suffix.lower() not in allowed:
                raise RuntimeError('unexpected_frontend_type: ' + relative.as_posix())
            actual[relative.as_posix()] = {'bytes': path.stat().st_size, 'sha256': BASE.digest(path)}
    if actual != manifest['files'] or len(actual) != manifest['file_count'] or manifest.get('nonliteral_dynamic_imports') != 0:
        raise RuntimeError('public_frontend_asset_set_changed')
    return manifest


def verify(source):
    """完整源码必须与冻结清单一致；本版只在前批结果上增加已批准的 embed 修复。"""
    lock = settings()
    expected = BASE.read_json(REPO / lock['source_manifest'])['files']
    actual = {}
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('release_source_symlink_not_allowed')
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        # 本版展开源码不含运行文件/依赖目录，避免把本机构建缓存或秘密打入公开归档。
        if path.name == '.env' or any(part in {'.git', '.build', 'node_modules', '__pycache__'} for part in path.relative_to(source).parts):
            raise RuntimeError('local_or_runtime_file_in_release_source')
        actual[relative] = {'bytes': path.stat().st_size, 'sha256': BASE.digest(path)}
    if actual != expected:
        raise RuntimeError('expanded_release_source_changed')
    public_assets(source / 'web/dist', lock)
    return lock


def prepare(archive, frontend, destination):
    """复用已验前端和原补丁链，仅向全新目录写源码；不执行 Vite 或旧测试。"""
    lock = settings()
    public_assets(frontend, lock)
    for patch in [lock['patches'][-1], lock['verification_patch']]:
        if BASE.digest(REPO / patch['file']) != patch['sha256']:
            raise RuntimeError('release_patch_changed')
    source = LOCAL.prepare(archive, destination, with_tests=True)
    if BASE.digest(source / 'main.go') != lock['approved_embed_change']['base_sha256']:
        raise RuntimeError('unexpected_main_before_embed_fix')
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(destination)}
    for patch in [lock['patches'][-1], lock['verification_patch']]:
        BASE.run(['git', '-c', 'core.autocrlf=false', 'apply', str(REPO / patch['file'])], source, env)
    dist = source / 'web/dist'
    if dist.is_symlink() or dist.resolve().parent != (source / 'web').resolve():
        raise RuntimeError('unexpected_owned_frontend_directory')
    shutil.rmtree(dist)
    shutil.copytree(frontend, dist)
    verify(source)
    BASE.write_json(destination / 'pkce9-preparation.json', {'application_version': lock['application_version'], 'published': False, 'frontend_reused': True})
    return source


def check_assets(source, cache, output):
    """只运行新增 main package embed.FS/HTTP 模块闭包检查；不运行旧业务测试。"""
    lock = verify(source)
    env = BASE.cache_environment(cache)
    env.update(CGO_ENABLED='0', GOEXPERIMENT='greenteagc', GOFLAGS='-mod=readonly', PKCE9_FRONTEND_MANIFEST=str(REPO / lock['frontend_manifest']))
    env.pop('GOOS', None)
    env.pop('GOARCH', None)
    go = shutil.which('go')
    if not go or subprocess.check_output([go, 'env', 'GOVERSION'], env=env, text=True, timeout=30).strip() != 'go1.26.1':
        raise RuntimeError('existing_go_1_26_1_required')
    command = [go, 'test', '.', '-run', '^TestPkce9PublicEmbeddedAssetClosure$', '-v', '-count=1', '-timeout=60s']
    result = subprocess.run(command, cwd=source, env=env, text=True, encoding='utf-8', capture_output=True, timeout=180)
    BASE.write_json(output, {'application_version': lock['application_version'], 'published': False, 'business_system_calls': False, 'command': command[1:], 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    print(result.stdout, end='')
    print(result.stderr, end='')
    if result.returncode:
        raise RuntimeError('real_embed_asset_closure_check_failed')


def build(source, cache, output):
    """校验并复用公开前端，仅为正式 Version 编译一次 Linux 二进制；不触发 Vite。"""
    lock = verify(source)
    identity = BASE.web_identity(source / 'web')
    if identity != lock['frontend_source_identity']:
        raise RuntimeError('frontend_source_identity_changed')
    frontend_cache = cache / 'frontend' / identity
    if not frontend_cache.exists():
        # 新主机也可复用对应源码内已核对的公开 dist，无需安装前端工具或重建。
        frontend_cache.mkdir(parents=True)
        shutil.copytree(source / 'web/dist', frontend_cache / 'dist')
        BASE.write_json(frontend_cache / 'files.json', BASE.file_manifest(frontend_cache / 'dist'))
    public_assets(frontend_cache / 'dist', lock)
    receipt = BASE.build(source, cache, output, application_version=lock['application_version'])
    if not receipt['frontend_cache_hit']:
        raise RuntimeError('release_must_not_rebuild_frontend')
    receipt.update(release_lock_sha256=BASE.digest(RELEASE / 'upstream.lock.json'), public_frontend_manifest_sha256=lock['frontend_manifest_sha256'])
    BASE.write_json(output / 'build-receipt.json', receipt)
    return receipt


def binary_assets(binary, lock):
    """直接核对 Linux amd64 ELF 的真实 embed 文件表，不执行二进制，不沿用旧版下划线过滤。"""
    data = binary.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\x3e\x00':
        raise RuntimeError('linux_amd64_elf_required')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', data, offset + index * size) for index in range(count)]
    segments = [segment for segment in segments if segment[0] == 1]

    def address(position):
        for segment in segments:
            if segment[2] <= position < segment[2] + segment[5]:
                return segment[3] + position - segment[2]
        raise RuntimeError('embedded_name_outside_load_segment')

    def content(pointer, length):
        for segment in segments:
            if segment[3] <= pointer and pointer + length <= segment[3] + segment[5]:
                start = segment[2] + pointer - segment[3]
                return data[start:start + length]
        return b''

    assets = BASE.read_json(REPO / lock['frontend_manifest'])['files']
    for name, expected in assets.items():
        encoded = ('web/dist/' + name).encode()
        found = False
        position = data.find(encoded)
        while position != -1 and not found:
            reference = struct.pack('<QQ', address(position), len(encoded))
            record = data.find(reference)
            while record != -1:
                pointer, length = struct.unpack_from('<QQ', data, record + 16)
                if length == expected['bytes'] and hashlib.sha256(content(pointer, length)).hexdigest() == expected['sha256']:
                    found = True
                    break
                record = data.find(reference, record + 1)
            position = data.find(encoded, position + 1)
        if not found:
            raise RuntimeError('linux_binary_embedded_asset_missing_or_changed: ' + name)
    return {'verified_public_files': len(assets), 'binary_sha256': BASE.digest(binary)}


def package(source, output, build_receipt, code_commit=None):
    """候选包覆盖精确任务 allowlist；公开包必须来自已提交同 SHA，排除其他本地工作。"""
    lock = verify(source)
    build = BASE.read_json(build_receipt)
    if build.get('application_version') != lock['application_version'] or not build.get('go_build_run') or not build.get('frontend_cache_hit') or build.get('release_lock_sha256') != BASE.digest(RELEASE / 'upstream.lock.json'):
        raise RuntimeError('formal_release_build_receipt_mismatch')
    binary = build_receipt.parent / 'new-api-linux-amd64'
    actual_binary = binary_assets(binary, lock)
    if build.get('binary_sha256') != actual_binary['binary_sha256']:
        raise RuntimeError('formal_release_binary_changed')
    if output.exists():
        raise RuntimeError('source_archive_already_exists')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True, timeout=30).strip()
    if code_commit is not None and (not re.fullmatch('[0-9a-f]{40}', code_commit) or code_commit != head):
        raise RuntimeError('source_commit_must_match_current_head')
    if code_commit is None and not output.name.endswith('.candidate.tar.gz'):
        raise RuntimeError('uncommitted_candidate_archive_name_required')
    if code_commit is not None and output.name != 'new-api-v0.13.2-pkce.9-corresponding-source.tar.gz':
        raise RuntimeError('published_source_archive_name_mismatch')
    recipe_tar = subprocess.check_output(['git', 'archive', '--format=tar', head], cwd=REPO, timeout=30)
    recipe = {}
    with tarfile.open(fileobj=io.BytesIO(recipe_tar)) as archive:
        for member in archive:
            if member.isfile():
                recipe[member.name] = archive.extractfile(member).read()
    inputs = BASE.read_json(RELEASE / 'release-inputs.json')['files']
    for name in inputs:
        path = REPO / name
        if not path.resolve().is_relative_to(REPO.resolve()) or path.is_symlink():
            raise RuntimeError('invalid_recipe_input_path')
        content = path.read_bytes()
        if code_commit is not None and recipe.get(name) != content:
            raise RuntimeError('release_recipe_not_committed: ' + name)
        recipe[name] = content
    # 其他未提交文档从未读入；两份既有工作只使用 git archive 内的已提交版本。
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for name, content in sorted(recipe.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(content))
        for path in sorted(source.rglob('*')):
            if path.is_file():
                archive.add(path, arcname='source/' + path.relative_to(source).as_posix())
    receipt = {'application_version': lock['application_version'], 'publishable': code_commit is not None, 'integration_commit': code_commit, 'recipe_base_commit': head, 'file': output.name, 'bytes': output.stat().st_size, 'sha256': BASE.digest(output), 'compiled_binary_sha256': actual_binary['binary_sha256'], 'linux_binary_public_files_verified': actual_binary['verified_public_files'], 'source_files_manifest_sha256': lock['source_manifest_sha256'], 'frontend_manifest_sha256': lock['frontend_manifest_sha256'], 'runtime_secrets_or_databases_included': False}
    BASE.write_json(output.with_suffix(output.suffix + '.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--base-archive', type=Path, required=True)
    preparation.add_argument('--frontend-dir', type=Path, required=True)
    preparation.add_argument('--destination', type=Path, required=True)
    for name in ('check-assets', 'build'):
        command = commands.add_parser(name)
        command.add_argument('--source', type=Path, required=True)
        command.add_argument('--cache-dir', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True)
    packaging = commands.add_parser('package')
    packaging.add_argument('--source', type=Path, required=True)
    packaging.add_argument('--output', type=Path, required=True)
    packaging.add_argument('--build-receipt', type=Path, required=True)
    packaging.add_argument('--code-commit')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.base_archive.resolve(), args.frontend_dir.resolve(), args.destination.resolve()))
    elif args.command == 'check-assets':
        check_assets(args.source.resolve(), args.cache_dir.resolve(), args.output.resolve())
    elif args.command == 'build':
        print(json.dumps(build(args.source.resolve(), args.cache_dir.resolve(), args.output.resolve()), indent=2))
    else:
        print(json.dumps(package(args.source.resolve(), args.output.resolve(), args.build_receipt.resolve(), args.code_commit), indent=2))
