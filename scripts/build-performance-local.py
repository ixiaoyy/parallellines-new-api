"""固定 pkce.8 基线的本地性能配方；不发布、不安装依赖、不改已发布锁。"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / 'patches/frontend-performance-manifest.json'


def digest(path):
    """返回构建输入/缓存产物摘要，只用于本地来源和缓存身份校验。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(command, cwd, env):
    """运行单次有界本地命令；失败向调用者保留，不尝试安装或改用其他版本。"""
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=1800)


def prepare(archive_path, destination):
    """校验固定对应源码后，仅向新目录解包 source/ 并应用独立性能补丁。"""
    manifest = read_json(MANIFEST)
    release = read_json(REPO / manifest['base_source_archive_manifest'])
    lock = read_json(REPO / manifest['base_release_lock'])
    if lock['application_version'] != release['application_version'] or release['application_version'] != 'v0.13.2-pkce.8':
        raise RuntimeError('unexpected_base_release')
    if destination.exists() or digest(archive_path) != release['sha256']:
        raise RuntimeError('base_archive_mismatch_or_destination_exists')
    patch = REPO / manifest['patch']
    if digest(patch) != manifest['patch_sha256']:
        raise RuntimeError('performance_patch_mismatch')
    source = destination / 'source'
    # 发布归档只接受普通源码文件；不跟随归档中的链接，也不允许越出新目录。
    with tarfile.open(archive_path) as archive:
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
        if (entry['base_sha256'] is None and path.exists()) or (entry['base_sha256'] is not None and digest(path) != entry['base_sha256']):
            raise RuntimeError('unexpected_base_file: ' + entry['path'])
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(destination.resolve())}
    run(['git', '-c', 'core.autocrlf=false', 'apply', '--check', str(patch)], source, env)
    run(['git', '-c', 'core.autocrlf=false', 'apply', str(patch)], source, env)
    verify_source(source)
    write_json(destination / 'local-source.json', {'published': False, 'application_version': manifest['application_version'], 'base_archive_sha256': release['sha256'], 'patch_sha256': manifest['patch_sha256']})
    return source


def verify_source(source):
    """构建前拒绝未应用当前性能补丁的源码，避免误把旧前端当优化产物。"""
    manifest = read_json(MANIFEST)
    for entry in manifest['files']:
        path = source / entry['path']
        if not path.is_file() or digest(path) != entry['result_sha256']:
            raise RuntimeError('prepared_source_changed: ' + entry['path'])


def web_identity(web):
    """以完整 Web 源码、配置和锁文件确定缓存身份，不包含依赖树与输出目录。"""
    items = []
    files = []
    for directory, children, names in os.walk(web):
        children[:] = [name for name in children if name not in {'node_modules', 'dist', '.git'}]
        files.extend(Path(directory) / name for name in names)
    for path in sorted(files):
        relative = path.relative_to(web)
        if not path.is_file():
            continue
        items.append((relative.as_posix(), digest(path)))
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()


def file_manifest(directory):
    return {p.relative_to(directory).as_posix(): digest(p) for p in sorted(directory.rglob('*')) if p.is_file()}


def frontend_summary(directory):
    """统计 HTML 静态入口及预加载资源的原始/逐文件 gzip 字节；不冒充页面 LCP。"""
    html = (directory / 'index.html').read_text(encoding='utf-8')
    paths = sorted(set(re.findall(r'(?:src|href)=[\"\'](/assets/[^\"\']+\.(?:js|css))[\"\']', html)))
    assets = []
    for name in paths:
        data = (directory / name.lstrip('/')).read_bytes()
        assets.append({'path': name, 'bytes': len(data), 'gzip_bytes': len(gzip.compress(data, mtime=0))})
    return {'scope': 'HTML entry and modulepreload JS/CSS; excludes lazy route payload', 'assets': assets, 'bytes': sum(a['bytes'] for a in assets), 'gzip_bytes': sum(a['gzip_bytes'] for a in assets)}


def cache_environment(cache):
    """跨发布目录复用 Go 模块/编译缓存；禁止隐式下载工具链和缺失模块。"""
    env = dict(os.environ)
    env.update(GOTOOLCHAIN='local', GOPROXY='off')
    go = shutil.which('go')
    defaults = json.loads(subprocess.check_output([go, 'env', '-json', 'GOCACHE', 'GOMODCACHE'], env=env, text=True)) if go else {}
    # 已有主机构建缓存优先，避免切到空目录反而重新下载/编译；无工具链时仅准备显式目录。
    env['GOCACHE'] = env.get('GOCACHE') or defaults.get('GOCACHE') or str(cache / 'go-build')
    env['GOMODCACHE'] = env.get('GOMODCACHE') or defaults.get('GOMODCACHE') or str(cache / 'go-mod')
    for name in ('GOCACHE', 'GOMODCACHE'):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    return env


def build(source, cache, output, frontend_only=False, web_deps=None, application_version=None):
    """复用匹配源码及产物身份的前端；只编译本地 Linux 二进制，不运行它或触碰服务。"""
    verify_source(source)
    if output.exists():
        raise RuntimeError('output_already_exists')
    env = cache_environment(cache)
    web = source / 'web'
    if cache.is_relative_to(web.resolve()) or output.is_relative_to(web.resolve()):
        raise RuntimeError('cache_and_output_must_be_outside_web_source')
    identity = web_identity(web)
    frontend_cache = cache / 'frontend' / identity
    cache_receipt = frontend_cache / 'files.json'
    cached_dist = frontend_cache / 'dist'
    started = time.monotonic()
    hit = cache_receipt.is_file() and cached_dist.is_dir() and read_json(cache_receipt) == file_manifest(cached_dist)
    if frontend_cache.exists() and not hit:
        raise RuntimeError('frontend_cache_incomplete_or_changed: ' + str(frontend_cache))
    if hit:
        # 新准备源码带着旧版 dist；命中时必须去掉旧资产，不能把两个版本一起嵌入二进制。
        dist = web / 'dist'
        if dist.exists():
            if dist.is_symlink() or dist.resolve().parent != web.resolve():
                raise RuntimeError('unexpected_frontend_output_path')
            shutil.rmtree(dist)
        shutil.copytree(cached_dist, web / 'dist', dirs_exist_ok=True)
    else:
        bun = shutil.which('bun')
        if not bun or subprocess.check_output([bun, '--version'], text=True).strip() != '1.4.4':
            raise RuntimeError('existing_bun_1_4_4_required; no_toolchain_download_performed')
        if web_deps and not (web / 'node_modules').exists():
            if not web_deps.is_dir() or web_deps.name != 'node_modules':
                raise RuntimeError('existing_node_modules_directory_required')
            os.symlink(web_deps, web / 'node_modules', target_is_directory=True)
        if not (web / 'node_modules').is_dir():
            raise RuntimeError('restore_frozen_bun_dependencies_first; this_script_does_not_install')
        # 本轮修改了前端，绝不拿 pkce.8 原资产冒充新产物；未来相同身份才可命中上述缓存。
        run([bun, 'run', 'build'], web, env)
        frontend_cache.mkdir(parents=True, exist_ok=True)
        shutil.copytree(web / 'dist', cached_dist, dirs_exist_ok=True)
        write_json(cache_receipt, file_manifest(cached_dist))
    web_seconds = time.monotonic() - started
    output.mkdir(parents=True)
    shutil.copytree(web / 'dist', output / 'web')
    receipt = {'published': False, 'application_version': application_version or read_json(MANIFEST)['application_version'], 'frontend_identity': identity, 'frontend_cache_hit': hit, 'frontend_seconds': round(web_seconds, 3), 'frontend': frontend_summary(output / 'web'), 'go_build_run': False, 'cache_paths': {k: env[k] for k in ('GOCACHE', 'GOMODCACHE')}}
    write_json(output / 'build-receipt.json', receipt)
    if not frontend_only:
        go = shutil.which('go')
        if not go or subprocess.check_output([go, 'env', 'GOVERSION'], env=env, text=True).strip() != 'go1.26.1':
            raise RuntimeError('existing_go_1_26_1_required; frontend_receipt_saved; no_toolchain_download_performed')
        env.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOEXPERIMENT='greenteagc')
        started = time.monotonic()
        version = receipt['application_version']
        run([go, 'build', '-mod=readonly', '-buildvcs=false', '-ldflags', '-s -w -X github.com/QuantumNous/new-api/common.Version=' + version, '-o', str(output / 'new-api-linux-amd64'), '.'], source, env)
        receipt.update(go_build_run=True, go_seconds=round(time.monotonic() - started, 3), binary_sha256=digest(output / 'new-api-linux-amd64'))
        write_json(output / 'build-receipt.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--base-archive', type=Path, required=True)
    preparation.add_argument('--destination', type=Path, required=True)
    compilation = commands.add_parser('build')
    compilation.add_argument('--source', type=Path, required=True)
    compilation.add_argument('--cache-dir', type=Path, required=True)
    compilation.add_argument('--output-dir', type=Path, required=True)
    compilation.add_argument('--web-deps', type=Path)
    compilation.add_argument('--frontend-only', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.base_archive.resolve(), args.destination.resolve()))
    else:
        print(json.dumps(build(args.source.resolve(), args.cache_dir.resolve(), args.output_dir.resolve(), args.frontend_only, args.web_deps.resolve() if args.web_deps else None), ensure_ascii=False, indent=2))
