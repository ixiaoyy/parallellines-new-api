#!/usr/bin/env python3
"""Deploy one reviewed New API binary. Run on the server with a nonsecret scope JSON.

Required keys: work_dir, archive, archive_sha256, binary_sha256, version, image,
expected_image, container, compose, database, receipt, status_url.
All artifacts/data/receipts must be under /data; compose may be under /opt.
No secret file is read and no database is restored automatically.
"""
import datetime
from contextlib import closing
import gzip
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import yaml

BASE_IMAGE = 'calciumion/new-api:v0.13.2@sha256:81da2c875f1de1460e6dd30324c5cb36b23ef55eaae00f317621fcb8a701ad43'
SERVICE = 'newapi'


class DeploymentError(RuntimeError):
    pass


def run(args):
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode:
        # Docker/Compose errors can expand environment values. Never persist them.
        raise DeploymentError('command_failed')
    return result.stdout


def sha256(file):
    digest = hashlib.sha256()
    with pathlib.Path(file).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def mapping_value(node, name):
    if not isinstance(node, yaml.MappingNode):
        raise DeploymentError('expected_mapping')
    matches = [value for key, value in node.value if key.value == name]
    if len(matches) != 1:
        raise DeploymentError('missing_or_duplicate_compose_key')
    return matches[0]


def render_compose(original, expected_image, new_image, relay_enabled):
    """Patch scalar spans only; preserve every unrelated byte, including Chat."""
    text = original.decode('utf-8')
    if any(isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(text)):
        raise DeploymentError('review_compose_anchors_before_deployment')
    node = yaml.compose(text)
    config = yaml.safe_load(text)
    services = mapping_value(node, 'services')
    api = mapping_value(services, SERVICE)
    service = config['services'][SERVICE]
    image = mapping_value(api, 'image')
    if not isinstance(image, yaml.ScalarNode) or service['image'] != expected_image:
        raise DeploymentError('unexpected_compose_image')
    if not service.get('env_file'):
        raise DeploymentError('missing_existing_secret_env_file')
    env = service.get('environment')
    if not isinstance(env, dict):
        raise DeploymentError('expected_environment_mapping')
    for key, expected in [('CUSTOM_OAUTH_PKCE_PROVIDERS', 'pingxingxian'),
                          ('CHANNEL_TEST_FREQUENCY', '0'),
                          ('GENERATE_DEFAULT_TOKEN', 'false')]:
        if str(env.get(key)).lower() != expected:
            raise DeploymentError('unexpected_existing_safety_environment')
    env_node = mapping_value(api, 'environment')
    if not isinstance(env_node, yaml.MappingNode) or not env_node.value or env_node.flow_style:
        raise DeploymentError('expected_block_environment')
    edits = [(image.start_mark.index, image.end_mark.index, json.dumps(new_image))]
    relay_key = 'CHAT_OAUTH_RELAY_ENABLED'
    value = json.dumps('true' if relay_enabled else 'false')
    if relay_key in env:
        relay_node = mapping_value(env_node, relay_key)
        if not isinstance(relay_node, yaml.ScalarNode):
            raise DeploymentError('invalid_relay_flag')
        edits.append((relay_node.start_mark.index, relay_node.end_mark.index, value))
    else:
        # end_mark can point after indentation of the following sibling key.
        insertion = text.rfind('\n', 0, env_node.end_mark.index) + 1
        if env_node.end_mark.index == len(text) and not text.endswith('\n'):
            insertion = len(text)
        newline = '\r\n' if '\r\n' in text else '\n'
        prefix = newline if insertion == len(text) and not text.endswith('\n') else ''
        indent = ' ' * env_node.value[0][0].start_mark.column
        edits.append((insertion, insertion, prefix + indent + relay_key + ': ' + value + newline))
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    updated = yaml.safe_load(text)
    expected = yaml.safe_load(original)
    expected['services'][SERVICE]['image'] = new_image
    expected['services'][SERVICE]['environment'][relay_key] = 'true' if relay_enabled else 'false'
    if updated != expected:
        raise DeploymentError('unintended_compose_change')
    if any(updated['services'][key] != value for key, value in config['services'].items() if key != SERVICE):
        raise DeploymentError('unintended_other_service_change')
    return text.encode('utf-8')


def verify_database_binding(original, mounts, database):
    """The rollback guard must inspect the exact database used by this service."""
    environment = yaml.safe_load(original)['services'][SERVICE].get('environment', {})
    if environment.get('SQLITE_PATH') != '/data/new-api.db':
        raise DeploymentError('unexpected_sqlite_container_path')
    data_mounts = [mount for mount in mounts if mount.get('Destination') == '/data']
    if len(data_mounts) != 1 or data_mounts[0].get('Type') != 'bind':
        raise DeploymentError('unexpected_database_mount')
    mounted_database = pathlib.Path(data_mounts[0]['Source']) / 'new-api.db'
    if mounted_database.resolve() != pathlib.Path(database).resolve():
        raise DeploymentError('scope_database_does_not_match_container_mount')


def internal_token_count(database):
    """Fail closed; count ALL non-null purpose rows, including deleted/disabled."""
    database = pathlib.Path(database)
    if not database.is_file() or database.is_symlink():
        raise DeploymentError('database_unavailable_for_rollback_guard')
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        columns = {row[1] for row in connection.execute('PRAGMA table_info(tokens)')}
        if not columns:
            raise DeploymentError('token_schema_unavailable')
        if 'internal_purpose' not in columns:
            return 0
        return connection.execute('SELECT COUNT(*) FROM tokens WHERE internal_purpose IS NOT NULL').fetchone()[0]


def rollback_allowed(database):
    try:
        return internal_token_count(database) == 0
    except Exception:
        return False


def data_path(value):
    candidate = pathlib.Path(value)
    if not candidate.is_absolute() or '..' in candidate.parts or candidate.parts[:2] != ('/', 'data'):
        raise DeploymentError('path_must_be_under_data')
    if any(part.is_symlink() for part in [candidate, *candidate.parents]):
        raise DeploymentError('symlink_path_rejected')
    return candidate


def validate_scope(scope):
    for key in ['archive_sha256', 'binary_sha256']:
        if not re.fullmatch('[a-f0-9]{64}', scope[key]):
            raise DeploymentError('invalid_hash')
    for key in ['image', 'expected_image', 'container', 'version']:
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:/@-]{0,240}', scope[key]):
            raise DeploymentError('invalid_identifier')
    if scope['image'] == scope['expected_image']:
        raise DeploymentError('new_image_must_be_distinct')
    for key in ['work_dir', 'archive', 'database', 'receipt']:
        data_path(scope[key])
    compose = pathlib.Path(scope['compose'])
    if not compose.is_absolute() or not compose.is_file() or compose.is_symlink():
        raise DeploymentError('invalid_compose_path')
    url = urllib.parse.urlsplit(scope['status_url'])
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path != '/api/status' or url.query or url.fragment or url.username or url.password:
        raise DeploymentError('status_must_be_loopback')


def wait_health(scope, attempts=35):
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(scope['status_url'], timeout=3) as response:
                result = json.load(response)
            if result.get('success') and result.get('data', {}).get('version') == scope['version']:
                return
        except Exception:
            pass
        time.sleep(1)
    raise DeploymentError('candidate_health_failed')


def isolated_smoke(image, version):
    smoke = run(['docker', 'run', '-d', '--network=none', '--read-only', '--memory=384m', '--cpus=0.5',
                 '--tmpfs', '/data:rw,noexec,nosuid,size=64m', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                 '-e', 'SQLITE_PATH=/data/smoke.db', '-e', 'GENERATE_DEFAULT_TOKEN=false',
                 '-e', 'CHANNEL_TEST_FREQUENCY=0', '-e', 'CHAT_OAUTH_RELAY_ENABLED=false', image]).strip()
    try:
        for _ in range(25):
            try:
                result = json.loads(run(['docker', 'exec', smoke, 'wget', '-qO-', 'http://127.0.0.1:3000/api/status']))
                if result.get('success') and result.get('data', {}).get('version') == version:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise DeploymentError('isolated_smoke_failed')
        setup = json.loads(run(['docker', 'exec', smoke, 'wget', '-qO-', 'http://127.0.0.1:3000/api/setup']))
        if setup.get('data', {}).get('root_init') is not False:
            raise DeploymentError('unexpected_smoke_account')
    finally:
        run(['docker', 'rm', '-f', smoke])


def save_private(path, contents):
    path = pathlib.Path(path)
    with path.open('wb') as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def recover(scope, original, proposed, compose_command):
    """Freeze minting before checking; never restore a DB, never erase purpose rows."""
    try:
        compose_command('stop', SERVICE)
    except Exception:
        return 'pending_recovery_stop_failed'
    if pathlib.Path(scope['compose']).read_bytes() not in (original, proposed):
        return 'pending_recovery_concurrent_compose_change_preserved'
    if rollback_allowed(scope['database']):
        try:
            save_private(scope['compose'], original)
            compose_command('config', '--quiet')
            compose_command('up', '-d', '--no-deps', '--no-build', SERVICE)
            return 'previous_image_restored_without_database_restore'
        except Exception:
            return 'pending_recovery_old_image_start_failed'
    # Any purpose row OR an unreadable schema prohibits the old binary.
    try:
        disabled = render_compose(proposed, scope['image'], scope['image'], False)
        save_private(scope['compose'], disabled)
        compose_command('config', '--quiet')
        compose_command('up', '-d', '--no-deps', '--no-build', SERVICE)
        wait_health(scope)
        return 'pending_recovery_guarded_image_running_relay_disabled'
    except Exception:
        try:
            compose_command('stop', SERVICE)
        except Exception:
            pass
        return 'pending_recovery_guarded_image_only_old_binary_forbidden'


def deploy(scope):
    os.umask(0o077)
    validate_scope(scope)
    receipt = data_path(scope['receipt'])
    if receipt.exists():
        raise DeploymentError('receipt_exists_inspect_before_retry')
    work = data_path(scope['work_dir'])
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    if work.stat().st_mode & 0o077:
        raise DeploymentError('work_directory_not_private')
    receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if receipt.parent.stat().st_mode & 0o077:
        raise DeploymentError('receipt_directory_not_private')
    archive = data_path(scope['archive'])
    if not archive.is_file() or sha256(archive) != scope['archive_sha256']:
        raise DeploymentError('archive_hash_mismatch')
    compose_path = pathlib.Path(scope['compose'])
    original = compose_path.read_bytes()
    proposed = render_compose(original, scope['expected_image'], scope['image'], True)
    def compose_command(*args):
        return run(['docker', 'compose', '-f', str(compose_path), *args])
    current_image = run(['docker', 'inspect', '--format', '{{.Config.Image}}', scope['container']]).strip()
    current_id = run(['docker', 'inspect', '--format', '{{.Id}}', scope['container']]).strip()
    compose_id = compose_command('ps', '-q', SERVICE).strip()
    if current_image != scope['expected_image'] or not compose_id or not current_id.startswith(compose_id):
        raise DeploymentError('current_container_or_image_changed')
    mounts = json.loads(run(['docker', 'inspect', '--format', '{{json .Mounts}}', scope['container']]))
    verify_database_binding(original, mounts, scope['database'])
    build = work / ('build-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    build.mkdir(mode=0o700)
    binary = build / 'new-api'
    with gzip.open(archive, 'rb') as source, binary.open('xb') as target:
        total = 0
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            total += len(chunk)
            if total > 256 * 1024 * 1024:
                raise DeploymentError('binary_too_large')
            target.write(chunk)
    if sha256(binary) != scope['binary_sha256']:
        raise DeploymentError('binary_hash_mismatch')
    binary.chmod(0o755)
    (build / 'Dockerfile').write_text('FROM ' + BASE_IMAGE + '\nCOPY --chmod=0755 new-api /new-api\n')
    run(['docker', 'build', '--pull=false', '--network=none', '-t', scope['image'], str(build)])
    isolated_smoke(scope['image'], scope['version'])
    backup = work / ('backup-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(mode=0o700)
    save_private(backup / 'compose.yaml', original)
    result = {'success': False, 'image': scope['image'], 'version': scope['version'],
              'binary_sha256': scope['binary_sha256'], 'backup': str(backup),
              'isolated_smoke_passed': True, 'database_restored': False}
    if compose_path.read_bytes() != original:
        raise DeploymentError('compose_changed_during_build')
    # Claim the receipt before the first live mutation. An interrupted run must
    # be inspected, not blindly retried.
    save_private(receipt, json.dumps({**result, 'state': 'activation_pending'}).encode())
    try:
        compose_command('stop', SERVICE)
        database = data_path(scope['database'])
        if not database.is_file():
            raise DeploymentError('database_missing')
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(str(backup / 'new-api.db'))) as target:
                source.backup(target)
        (backup / 'new-api.db').chmod(0o600)
        if compose_path.read_bytes() != original:
            raise DeploymentError('compose_changed_during_backup')
        save_private(compose_path, proposed)
        compose_command('config', '--quiet')
        compose_command('up', '-d', '--no-deps', '--no-build', SERVICE)
        wait_health(scope)
        result.update(success=True, state='healthy_relay_enabled')
    except Exception as error:
        result['failure_code'] = str(error) if isinstance(error, DeploymentError) else 'unexpected_activation_failure'
        result['state'] = recover(scope, original, proposed, compose_command)
    result['time_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_private(receipt, json.dumps(result, indent=2).encode())
    print(json.dumps(result))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise DeploymentError('usage_requires_nonsecret_scope_json')
        with open(sys.argv[1], encoding='utf-8') as scope_file:
            exit_code = deploy(json.load(scope_file))
    except Exception as error:
        # Never include raw exceptions/command output/config values.
        print(json.dumps({'success': False, 'state': 'preflight_or_tool_failure',
                          'error_type': type(error).__name__,
                          'error_code': str(error) if isinstance(error, DeploymentError) else 'unexpected_failure'}))
        exit_code = 1
    sys.exit(exit_code)
