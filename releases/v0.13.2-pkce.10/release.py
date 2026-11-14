"""pkce.10 固定 pkce.9 的完整来源与增量补丁；仅本地准备、离线构建和对应源码打包。"""
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
import tarfile
import time

RELEASE = Path(__file__).resolve().parent
REPO = RELEASE.parent.parent
SPEC = importlib.util.spec_from_file_location('pkce9_recipe', REPO / 'releases/v0.13.2-pkce.9/release.py')
PREVIOUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIOUS)
BASE = PREVIOUS.BASE
PREVIOUS.RELEASE = RELEASE  # 只复用无版本常量的公开资产及 ELF 检查，不执行旧构建/旧源码断言。


def settings():
    """校验独立锁、完整基线及本轮增量，不改历史发布配方。"""
    lock = BASE.read_json(RELEASE / 'upstream.lock.json')
    for key in ('base_source_manifest', 'profile_manifest', 'frontend_manifest', 'source_manifest'):
        if BASE.digest(REPO / lock[key]) != lock[key + '_sha256']:
            raise RuntimeError('release_manifest_changed: ' + key)
    for entry in lock['patches']:
        if BASE.digest(REPO / entry['file']) != entry['sha256']:
            raise RuntimeError('release_patch_changed')
    return lock


def file_set(source):
    """只接受普通公开源码文件，不跟随链接，也不收集环境、依赖、缓存或运行目录。"""
    actual = {}
    for directory, children, names in os.walk(source):
        for name in children:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction() or name in {'.git', '.build', 'node_modules', '__pycache__'}:
                raise RuntimeError('local_or_link_directory_in_source: ' + name)
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or name == '.env':
                raise RuntimeError('private_or_link_file_in_source')
            actual[path.relative_to(source).as_posix()] = {'bytes': path.stat().st_size, 'sha256': BASE.digest(path)}
    return actual


def verify(source):
    """完整展开源码与已冻结前端必须逐项一致，新增文件也必须经过清单批准。"""
    lock = settings()
    if file_set(source) != BASE.read_json(REPO / lock['source_manifest'])['files']:
        raise RuntimeError('expanded_release_source_changed')
    PREVIOUS.public_assets(source / 'web/dist', lock)
    if BASE.web_identity(source / 'web') != lock['frontend_source_identity']:
        raise RuntimeError('frontend_source_identity_changed')
    return lock


def prepare(base, frontend, destination):
    """只向全新目录复制已核验 pkce.9，再顺序应用生产/测试补丁及精确新前端；不安装、不联网。"""
    lock = settings()
    expected = BASE.read_json(REPO / lock['base_source_manifest'])['files']
    if file_set(base) != expected or destination.exists():
        raise RuntimeError('base_source_mismatch_or_destination_exists')
    PREVIOUS.public_assets(frontend, lock)
    source = destination / 'source'
    for name in expected:
        if name.startswith('web/dist/'):
            continue
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / name, target)
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(destination.resolve())}
    for entry in lock['patches']:
        patch = str(REPO / entry['file'])
        for command in (['git', '-c', 'core.autocrlf=false', 'apply', '--check', patch], ['git', '-c', 'core.autocrlf=false', 'apply', patch]):
            subprocess.run(command, cwd=source, env=env, check=True, timeout=30)
    shutil.copytree(frontend, source / 'web/dist')
    verify(source)
    return source


def build(source, cache, output):
    """只使用现有 Go 1.26.1 与离线模块缓存，编译 Linux amd64；不重新生成/混入旧前端。"""
    lock = verify(source)
    if output.exists():
        raise RuntimeError('output_already_exists')
    env = BASE.cache_environment(cache)
    go = shutil.which('go')
    if not go or subprocess.check_output([go, 'env', 'GOVERSION'], env=env, text=True, timeout=30).strip() != 'go1.26.1':
        raise RuntimeError('existing_go_1_26_1_required')
    env.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOEXPERIMENT='greenteagc', GOSUMDB='off')
    output.mkdir(parents=True)
    start = time.monotonic()
    subprocess.run([go, 'build', '-mod=readonly', '-buildvcs=false', '-ldflags', '-s -w -X github.com/QuantumNous/new-api/common.Version=' + lock['application_version'], '-o', str(output / 'new-api-linux-amd64'), '.'], cwd=source, env=env, check=True, timeout=1800)
    embedded = PREVIOUS.binary_assets(output / 'new-api-linux-amd64', lock)
    receipt = {'application_version': lock['application_version'], 'published': False, 'go_build_run': True, 'go_seconds': round(time.monotonic() - start, 3), 'release_lock_sha256': BASE.digest(RELEASE / 'upstream.lock.json'), 'frontend_manifest_sha256': lock['frontend_manifest_sha256'], 'binary_sha256': embedded['binary_sha256'], 'verified_public_files': embedded['verified_public_files']}
    BASE.write_json(output / 'build-receipt.json', receipt)
    return receipt


def package(source, output, receipt_path, code_commit=None):
    """候选包明确不可发布；正式包须所有本轮输入均来自同一已提交 HEAD，且包含精确对应源码。"""
    # 正式交付名称沿原发布合同包含精确版本，防止内容是 .10 却以旧版本归档名发布。
    if code_commit is not None and output.name != 'new-api-v0.13.2-pkce.10-corresponding-source.tar.gz':
        raise RuntimeError('published_source_archive_name_mismatch')
    lock = verify(source)
    receipt = BASE.read_json(receipt_path)
    binary = PREVIOUS.binary_assets(receipt_path.parent / 'new-api-linux-amd64', lock)
    if not receipt.get('go_build_run') or receipt.get('application_version') != lock['application_version'] or receipt.get('release_lock_sha256') != BASE.digest(RELEASE / 'upstream.lock.json') or receipt.get('binary_sha256') != binary['binary_sha256']:
        raise RuntimeError('release_build_receipt_mismatch')
    if output.exists():
        raise RuntimeError('source_archive_already_exists')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True, timeout=30).strip()
    if code_commit is not None and (not re.fullmatch('[0-9a-f]{40}', code_commit) or code_commit != head):
        raise RuntimeError('source_commit_must_match_current_head')
    if code_commit is None and not output.name.endswith('.candidate.tar.gz'):
        raise RuntimeError('uncommitted_candidate_archive_name_required')
    recipe = {}
    raw = subprocess.check_output(['git', 'archive', '--format=tar', head], cwd=REPO, timeout=30)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.isfile():
                recipe[member.name] = archive.extractfile(member).read()
    for name in BASE.read_json(RELEASE / 'release-inputs.json')['files']:
        path = REPO / name
        if not path.resolve().is_relative_to(REPO.resolve()) or path.is_symlink():
            raise RuntimeError('invalid_recipe_input_path')
        content = path.read_bytes()
        if code_commit is not None and recipe.get(name) != content:
            raise RuntimeError('release_recipe_not_committed: ' + name)
        recipe[name] = content
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for name, content in sorted(recipe.items()):
            entry = tarfile.TarInfo(name); entry.size = len(content); entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(content))
        for name in sorted(BASE.read_json(REPO / lock['source_manifest'])['files']):
            archive.add(source / name, arcname='source/' + name, recursive=False)
    result = {'application_version': lock['application_version'], 'publishable': code_commit is not None, 'integration_commit': code_commit, 'recipe_base_commit': head, 'sha256': BASE.digest(output), 'bytes': output.stat().st_size, 'binary_sha256': binary['binary_sha256']}
    BASE.write_json(output.with_name(output.name + '.json'), result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--base-source', type=Path, required=True); prep.add_argument('--frontend-dir', type=Path, required=True); prep.add_argument('--destination', type=Path, required=True)
    check = commands.add_parser('verify'); check.add_argument('--source', type=Path, required=True)
    compile = commands.add_parser('build'); compile.add_argument('--source', type=Path, required=True); compile.add_argument('--cache-dir', type=Path, required=True); compile.add_argument('--output-dir', type=Path, required=True)
    pack = commands.add_parser('package'); pack.add_argument('--source', type=Path, required=True); pack.add_argument('--output', type=Path, required=True); pack.add_argument('--build-receipt', type=Path, required=True); pack.add_argument('--code-commit')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.base_source.resolve(), args.frontend_dir.resolve(), args.destination.resolve()))
    elif args.command == 'verify':
        print(json.dumps({'application_version': verify(args.source.resolve())['application_version'], 'verified': True}))
    elif args.command == 'build':
        print(json.dumps(build(args.source.resolve(), args.cache_dir.resolve(), args.output_dir.resolve()), indent=2))
    else:
        print(json.dumps(package(args.source.resolve(), args.output.resolve(), args.build_receipt.resolve(), args.code_commit), indent=2))
