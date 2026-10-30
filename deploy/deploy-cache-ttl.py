"""仅将现有 pkce.5 升级到缓存时长修复 pkce.6，不运行离线验证或模型请求。"""
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.request

import yaml

spec = importlib.util.spec_from_file_location('relay_deployment', Path(__file__).with_name('deploy-personal-relay.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def run(args, timeout=120):
    """有界执行部署命令；异常只返回固定原因，避免展开环境中的密钥。"""
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('deployment_command_failed')
    return result.stdout.decode().strip()


def healthy(url, version):
    """检查真实服务版本，不调用模型；最多等待两分钟。"""
    deadline = time.monotonic() + 120
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                value = json.load(response)
            if value.get('success') and value.get('data', {}).get('version') == version:
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('runtime_version_or_health_failed')
        time.sleep(3)


def replace_image(path, expected_service, old, new):
    """锁定并条件更新目标服务镜像，保留并发修改的其他服务与文件 inode。"""
    with path.open('r+b') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        original = stream.read()
        if yaml.safe_load(original)['services']['newapi'] != expected_service:
            raise RuntimeError('target_service_changed_concurrently')
        opened, current = os.fstat(stream.fileno()), path.stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError('compose_inode_changed')
        replacement = base.render_compose(original, old, new, True)
        stream.seek(0)
        stream.write(replacement)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def deploy(scope):
    """读取非敏感范围文件；保留私有恢复点，只修改 New API 镜像这一标量。"""
    os.umask(0o077)
    work = base.data_path(scope['work_dir'])
    binary = base.data_path(scope['binary'])
    database = base.data_path(scope['database'])
    old, new = 'parallellines-newapi:v0.13.2-pkce.5', 'parallellines-newapi:v0.13.2-pkce.6'
    container = scope['container']
    compose = Path(scope['compose'])
    original = compose.read_bytes()
    proposed = base.render_compose(original, old, new, True)
    service = yaml.safe_load(original)['services']['newapi']
    for key in ('OPENAI_STANDARD_BILLING_ENABLED', 'MAIN_OAUTH_PROFILE_SYNC_ENABLED'):
        if str(service['environment'].get(key)).lower() != 'true':
            raise RuntimeError('existing_policy_must_remain_enabled')
    if base.sha256(binary) != scope['binary_sha256']:
        raise RuntimeError('binary_hash_mismatch')
    if run(['docker', 'inspect', '--format', '{{.Image}}', container]) != scope['expected_image_id']:
        raise RuntimeError('runtime_image_changed')
    mounts = json.loads(run(['docker', 'inspect', '--format', '{{json .Mounts}}', container]))
    base.verify_database_binding(original, mounts, str(database))
    healthy(scope['status_url'], 'v0.13.2-pkce.5')
    if run(['docker', 'image', 'ls', '--quiet', new]):
        raise RuntimeError('release_tag_exists_inspect_before_retry')
    context = work / 'image'
    context.mkdir(mode=0o700)
    (context / 'new-api').write_bytes(binary.read_bytes())
    base_tag = new + '-base'
    run(['docker', 'image', 'tag', scope['expected_image_id'], base_tag])
    (context / 'Dockerfile').write_text('FROM ' + base_tag + '\nCOPY --chmod=0755 new-api /new-api\n')
    run(['docker', 'build', '--pull=false', '--network=none', '-t', new, str(context)], timeout=300)
    backup = work / 'activation-backup'
    backup.mkdir(mode=0o700)
    base.save_private(backup / 'compose.yaml', original)
    # 在线 SQLite backup 生成一致私有快照，不修改业务库；恢复镜像时不回灌数据库。
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5) as source:
        with sqlite3.connect(str(backup / 'new-api.db')) as target:
            deadline = time.monotonic() + 30
            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise RuntimeError('database_backup_deadline_exceeded')
            source.backup(target, pages=256, sleep=0.05, progress=progress)
    command = ['docker', 'compose', '--project-name', scope['project'], '-f', str(compose)]
    if compose.read_bytes() != original:
        raise RuntimeError('compose_changed_before_activation')
    result = {'success': False, 'image': new, 'binary_sha256': scope['binary_sha256'],
              'backup': str(backup), 'source_commit': scope['source_commit'],
              'offline_validation_run': False, 'model_requests': 0, 'database_restored': False}
    try:
        replace_image(compose, service, old, new)
        run(command + ['config', '--quiet'])
        run(command + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'newapi'])
        healthy(scope['status_url'], 'v0.13.2-pkce.6')
        if run(['docker', 'exec', container, 'sha256sum', '/new-api']).split()[0] != scope['binary_sha256']:
            raise RuntimeError('runtime_binary_mismatch')
        run(['docker', 'exec', container, 'sh', '-c',
             'test "$OPENAI_STANDARD_BILLING_ENABLED" = true && test "$MAIN_OAUTH_PROFILE_SYNC_ENABLED" = true && test "$CHAT_OAUTH_RELAY_ENABLED" = true'])
        result['success'] = True
    except Exception as error:
        result['failure_type'] = type(error).__name__
        result['rollback_healthy'] = False
        # 只反转本次镜像标量，保留其他服务及并发维护；目标服务本身有变化则拒绝覆盖。
        current = compose.read_bytes()
        current_service = yaml.safe_load(current)['services']['newapi']
        expected_service = yaml.safe_load(proposed)['services']['newapi']
        if current_service == expected_service:
            try:
                replace_image(compose, expected_service, new, old)
                run(command + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'newapi'])
                healthy(scope['status_url'], 'v0.13.2-pkce.5')
                result['rollback_healthy'] = True
            except Exception:
                pass
    result['time_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    base.save_private(work / 'receipt.json', json.dumps(result, indent=2).encode())
    print(json.dumps(result), flush=True)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    try:
        code = deploy(json.loads(Path(sys.argv[1]).read_text()))
    except Exception as error:
        print(json.dumps({'success': False, 'failure_type': type(error).__name__, 'state': 'preflight_or_preparation_stopped'}))
        code = 1
    raise SystemExit(code)
