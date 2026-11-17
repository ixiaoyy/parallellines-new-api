"""将当前 pkce.10 对应源码与精确 Git 配方打包；不安装、上传或执行远程操作。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[2]
LOCK_PATH = 'releases/v0.13.2-pkce.10/upstream.lock.json'


def digest(data):
    """返回已读取公开字节的 SHA-256，绑定归档与同次构建输入。"""
    return hashlib.sha256(data).hexdigest()


def git_bytes(revision, name):
    """只读取显式提交中的配方文件；revision 为完整提交 ID，不读取工作区或远端。"""
    return subprocess.check_output(['git', 'show', revision + ':' + name], cwd=REPO, timeout=30)


def public_path(name):
    """校验源码相对路径，拒绝密钥、真实环境、用户数据库、缓存和调试产物。"""
    path = Path(name)
    private_parts = {'.git', '.build', '.private', 'node_modules', '__pycache__', 'secrets', 'logs'}
    forbidden_suffixes = {'.pem', '.key', '.db', '.sqlite', '.sqlite3', '.log', '.pyc', '.map', '.zip', '.gz'}
    if path.is_absolute() or '..' in path.parts or any(part in private_parts for part in path.parts):
        raise RuntimeError('non_public_archive_path: ' + name)
    if path.suffix.lower() in forbidden_suffixes or ('.env' in path.name and not path.name.endswith('.env.example')):
        raise RuntimeError('private_or_debug_archive_file: ' + name)


def package(source, build, revision, output):
    """打包已冻结源码和新提交配方；参数为原源码、构建目录、完整提交及全新输出，返回公开产物摘要。"""
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise RuntimeError('full_source_revision_required')
    resolved = subprocess.check_output(['git', 'rev-parse', '--verify', revision + '^{commit}'], cwd=REPO, text=True, timeout=30).strip()
    if resolved != revision:
        raise RuntimeError('source_revision_mismatch')
    if not output.resolve().is_relative_to((REPO / 'dist').resolve()) or not output.name.endswith('.tar.gz'):
        raise RuntimeError('new_dist_archive_required')
    partial = output.with_name(output.name + '.partial')
    if output.exists() or partial.exists() or output.is_symlink():
        raise RuntimeError('archive_output_already_exists')

    lock_data = git_bytes(revision, LOCK_PATH)
    lock = json.loads(lock_data)
    if (REPO / LOCK_PATH).read_bytes() != lock_data:
        raise RuntimeError('working_release_lock_not_committed_revision')
    manifest_data = git_bytes(revision, lock['source_manifest'])
    if digest(manifest_data) != lock['source_manifest_sha256']:
        raise RuntimeError('committed_source_manifest_mismatch')
    expected = json.loads(manifest_data)['files']
    receipt_data = (build / 'build-receipt.json').read_bytes()
    receipt = json.loads(receipt_data)
    binary_data = (build / 'new-api-linux-amd64').read_bytes()
    if receipt['application_version'] != lock['application_version'] or receipt['release_lock_sha256'] != digest(lock_data):
        raise RuntimeError('build_receipt_release_mismatch')
    if receipt['frontend_manifest_sha256'] != lock['frontend_manifest_sha256'] or receipt['binary_sha256'] != digest(binary_data):
        raise RuntimeError('build_receipt_artifact_mismatch')

    # 只接受冻结清单中的完整目录；额外文件和链接不能混入公开源码。
    actual = []
    for path in source.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError('source_link_not_allowed')
        if path.is_file():
            actual.append(path.relative_to(source).as_posix())
    if set(actual) != set(expected):
        raise RuntimeError('prepared_source_file_set_changed')
    archive_data = subprocess.check_output(['git', 'archive', '--format=tar', revision], cwd=REPO, timeout=60)
    recipe = []
    with tarfile.open(fileobj=io.BytesIO(archive_data), mode='r:') as snapshot:
        for entry in snapshot.getmembers():
            if entry.isdir():
                continue
            public_path(entry.name)
            if not entry.isfile():
                raise RuntimeError('recipe_link_or_special_file_not_allowed')
            recipe.append((entry.name, snapshot.extractfile(entry).read(), entry.mode))

    prefix = 'new-api-' + lock['application_version'] + '-i18n-' + revision[:12]
    metadata = {
        'application_version': lock['application_version'], 'source_revision': revision,
        'release_lock_sha256': digest(lock_data), 'source_manifest_sha256': digest(manifest_data),
        'frontend_manifest_sha256': lock['frontend_manifest_sha256'],
        'binary_sha256': receipt['binary_sha256'], 'source_files': len(expected), 'recipe_files': len(recipe),
    }
    instructions = (
        '# Exact corresponding source\n\n'
        'Source revision: `' + revision + '`. Application version: `' + lock['application_version'] + '`.\n\n'
        '`source/` contains the complete frozen upstream source, applied patches, dependency lockfiles and ' + str(receipt['verified_public_files']) + ' embedded frontend files. '
        '`recipe/` is the exact Git snapshot with ordered release patches, manifests, build instructions and original licenses/notices.\n\n'
        'Use `python recipe/releases/v0.13.2-pkce.10/release.py verify --source source` to inspect these inputs. '
        'With existing Go 1.26.1 and module cache, run the same recipe `build --source source --cache-dir <existing-cache> --output-dir <new-output>`. '
        'The builder uses linux/amd64, CGO=0 and offline dependencies. See the versioned README and Dockerfile.runtime; do not use the reusable root pkce.3 recipe.\n\n'
        'No runtime secrets, real environment files, databases, dependency caches or debug logs are included. '
        'This archive records technical source correspondence and does not make a legal-compliance conclusion.\n'
    ).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(partial, 'w:gz', compresslevel=6) as target:
        def add(name, data, mode=0o644):
            """写入已核验字节，不沿宿主链接读取额外数据，也不记录宿主用户名。"""
            info = tarfile.TarInfo(prefix + '/' + name)
            info.size, info.mode, info.mtime = len(data), mode, 0
            target.addfile(info, io.BytesIO(data))

        for name in sorted(expected):
            public_path(name)
            data = (source / name).read_bytes()
            if expected[name] != {'bytes': len(data), 'sha256': digest(data)}:
                raise RuntimeError('prepared_source_changed: ' + name)
            add('source/' + name, data, 0o755 if name.endswith('.sh') else 0o644)
        for name, data, mode in recipe:
            add('recipe/' + name, data, mode)
        add('BUILD.md', instructions)
        add('release.json', (json.dumps(metadata, indent=2) + '\n').encode())
        add('build-receipt.json', receipt_data)
    partial.replace(output)
    result = {**metadata, 'archive': output.name, 'archive_bytes': output.stat().st_size, 'archive_sha256': digest(output.read_bytes())}
    output.with_name(output.name + '.sha256').write_text(result['archive_sha256'] + '  ' + output.name + '\n', encoding='utf-8')
    output.with_name(output.name + '.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.source.resolve(), args.build_dir.resolve(), args.revision, args.output.resolve()), indent=2))
