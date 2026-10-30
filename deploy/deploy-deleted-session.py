#!/usr/bin/env python3
"""Forward-only pkce.4 -> pkce.5 deleted-account-cookie fix.

No provider, user, role, quota or credential writes. The only database operation
is a consistent private backup. The exact separately approved account deletion
is not part of this helper. Keep deploy-personal-relay.py alongside this file.
"""
import datetime
from contextlib import closing
import gzip
import importlib.util
import json
import os
import pathlib
import sqlite3
import sys
import time

import yaml

SPEC = importlib.util.spec_from_file_location('relay_deployment', pathlib.Path(__file__).with_name('deploy-personal-relay.py'))
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
DeploymentError = base.DeploymentError
OLD_IMAGE = 'parallellines-newapi:v0.13.2-pkce.4'
NEW_IMAGE = 'parallellines-newapi:v0.13.2-pkce.5'
VERSION = 'v0.13.2-pkce.5'


def render_compose(original, expected_image, relay_enabled=True):
    """Normal activation changes only the image; recovery also disables relay."""
    env = yaml.safe_load(original)['services']['newapi']['environment']
    for key in ('OPENAI_STANDARD_BILLING_ENABLED', 'MAIN_OAUTH_PROFILE_SYNC_ENABLED'):
        if str(env.get(key)).lower() != 'true':
            raise DeploymentError('existing_billing_and_profile_policies_must_remain_enabled')
    if str(env.get('CHAT_OAUTH_RELAY_ENABLED')).lower() != 'true':
        raise DeploymentError('expected_existing_relay_enabled')
    return base.render_compose(original, expected_image, NEW_IMAGE, relay_enabled)


def validate_scope(scope):
    base.validate_scope(scope)
    if (scope['expected_image'], scope['image'], scope['version']) != (OLD_IMAGE, NEW_IMAGE, VERSION):
        raise DeploymentError('only_reviewed_pkce4_to_pkce5_upgrade_allowed')


def verify_runtime(scope, relay_enabled):
    image = base.run(['docker', 'inspect', '--format', '{{.Config.Image}}', scope['container']]).strip()
    if image != NEW_IMAGE:
        raise DeploymentError('deleted_session_image_not_active')
    expected_relay = 'true' if relay_enabled else 'false'
    script = ('test "$MAIN_OAUTH_PROFILE_SYNC_ENABLED" = true && '
              'test "$OPENAI_STANDARD_BILLING_ENABLED" = true && '
              'test "$CHAT_OAUTH_RELAY_ENABLED" = ' + expected_relay + ' && '
              'test "$CHANNEL_TEST_FREQUENCY" = 0 && '
              'test "$GENERATE_DEFAULT_TOKEN" = false && '
              'test "$CUSTOM_OAUTH_PKCE_PROVIDERS" = pingxingxian')
    base.run(['docker', 'exec', scope['container'], 'sh', '-c', script])


def stop_and_verify(scope, compose_command):
    compose_command('stop', 'newapi')
    if base.run(['docker', 'inspect', '--format', '{{.State.Running}}', scope['container']]).strip() != 'false':
        raise DeploymentError('newapi_stop_not_confirmed')


def backup_database(database, destination):
    """Read the exact stopped-service DB without issuing any mutation to it."""
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
        source.execute('PRAGMA query_only=ON')
        with closing(sqlite3.connect(str(destination))) as target:
            source.backup(target)
    destination.chmod(0o600)


def isolated_smoke():
    smoke = base.run(['docker', 'run', '-d', '--network=none', '--read-only', '--memory=384m', '--cpus=0.5',
                      '--tmpfs', '/data:rw,noexec,nosuid,size=64m', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                      '-e', 'SQLITE_PATH=/data/smoke.db', '-e', 'GENERATE_DEFAULT_TOKEN=false',
                      '-e', 'CHANNEL_TEST_FREQUENCY=0', '-e', 'CHAT_OAUTH_RELAY_ENABLED=false',
                      '-e', 'OPENAI_STANDARD_BILLING_ENABLED=true',
                      '-e', 'MAIN_OAUTH_PROFILE_SYNC_ENABLED=true', NEW_IMAGE]).strip()
    try:
        for _ in range(25):
            try:
                result = json.loads(base.run(['docker', 'exec', smoke, 'wget', '-qO-', 'http://127.0.0.1:3000/api/status']))
                if result.get('success') and result.get('data', {}).get('version') == VERSION:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise DeploymentError('isolated_deleted_session_smoke_failed')
        setup = json.loads(base.run(['docker', 'exec', smoke, 'wget', '-qO-', 'http://127.0.0.1:3000/api/setup']))
        if setup.get('data', {}).get('root_init') is not False:
            raise DeploymentError('unexpected_smoke_account')
    finally:
        base.run(['docker', 'rm', '-f', smoke])


def recover(scope, original, proposed, compose_command):
    """Never restore a database or reactivate the old cookie-vulnerable binary."""
    try:
        stop_and_verify(scope, compose_command)
    except Exception:
        return 'pending_recovery_stop_unconfirmed'
    current = pathlib.Path(scope['compose']).read_bytes()
    if current not in (original, proposed):
        return 'pending_recovery_concurrent_compose_change_preserved'
    try:
        disabled = render_compose(proposed, NEW_IMAGE, False)
        base.save_private(scope['compose'], disabled)
        compose_command('config', '--quiet')
        compose_command('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'newapi')
        base.wait_health(scope)
        verify_runtime(scope, False)
        return 'pending_recovery_pkce5_policies_retained_relay_disabled'
    except Exception:
        try:
            stop_and_verify(scope, compose_command)
        except Exception:
            return 'pending_recovery_pkce5_stop_unconfirmed'
        return 'pending_recovery_pkce5_stopped_operator_required'


def deploy(scope):
    os.umask(0o077)
    validate_scope(scope)
    receipt = base.data_path(scope['receipt'])
    if receipt.exists():
        raise DeploymentError('receipt_exists_inspect_before_retry')
    work = base.data_path(scope['work_dir'])
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if work.stat().st_mode & 0o077 or receipt.parent.stat().st_mode & 0o077:
        raise DeploymentError('work_and_receipts_must_be_private')
    archive = base.data_path(scope['archive'])
    if not archive.is_file() or base.sha256(archive) != scope['archive_sha256']:
        raise DeploymentError('archive_hash_mismatch')
    compose_path = pathlib.Path(scope['compose'])
    original = compose_path.read_bytes()
    proposed = render_compose(original, OLD_IMAGE)

    def compose_command(*args):
        return base.run(['docker', 'compose', '-f', str(compose_path), *args])

    current_image = base.run(['docker', 'inspect', '--format', '{{.Config.Image}}', scope['container']]).strip()
    current_id = base.run(['docker', 'inspect', '--format', '{{.Id}}', scope['container']]).strip()
    compose_id = compose_command('ps', '-q', 'newapi').strip()
    if current_image != OLD_IMAGE or not compose_id or not current_id.startswith(compose_id):
        raise DeploymentError('current_container_or_image_changed')
    mounts = json.loads(base.run(['docker', 'inspect', '--format', '{{json .Mounts}}', scope['container']]))
    base.verify_database_binding(original, mounts, scope['database'])
    database = base.data_path(scope['database'])
    if not database.is_file():
        raise DeploymentError('database_missing')
    if base.run(['docker', 'image', 'ls', '--quiet', NEW_IMAGE]).strip():
        raise DeploymentError('new_image_exists_inspect_before_retry')
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
    if base.sha256(binary) != scope['binary_sha256']:
        raise DeploymentError('binary_hash_mismatch')
    binary.chmod(0o755)
    (build / 'Dockerfile').write_text('FROM ' + base.BASE_IMAGE + '\nCOPY --chmod=0755 new-api /new-api\n')
    base.run(['docker', 'build', '--pull=false', '--network=none', '-t', NEW_IMAGE, str(build)])
    isolated_smoke()
    backup = work / ('backup-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(mode=0o700)
    base.save_private(backup / 'compose.yaml', original)
    result = {'success': False, 'image': NEW_IMAGE, 'version': VERSION,
              'binary_sha256': scope['binary_sha256'], 'backup': str(backup),
              'isolated_smoke_passed': True, 'database_restored': False,
              'provider_scope_written': False, 'users_written': False,
              'roles_or_balances_written': False, 'credentials_written': False,
              'existing_billing_and_profile_policies_retained': True,
              'session_fix_scope': 'deleted_accounts_only', 'account_deletion_performed': False}
    if compose_path.read_bytes() != original:
        raise DeploymentError('compose_changed_during_build')
    base.save_private(receipt, json.dumps({**result, 'state': 'activation_pending'}).encode())
    try:
        stop_and_verify(scope, compose_command)
        database = base.data_path(scope['database'])
        if not database.is_file():
            raise DeploymentError('database_missing')
        backup_database(database, backup / 'new-api.db')
        if compose_path.read_bytes() != original:
            raise DeploymentError('compose_changed_during_backup')
        base.save_private(compose_path, proposed)
        compose_command('config', '--quiet')
        compose_command('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'newapi')
        base.wait_health(scope)
        verify_runtime(scope, True)
        result.update(success=True, state='healthy_deleted_session_fix_enabled')
    except Exception as error:
        result['failure_code'] = str(error) if isinstance(error, DeploymentError) else 'unexpected_activation_failure'
        result['state'] = recover(scope, original, proposed, compose_command)
    result['time_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    base.save_private(receipt, json.dumps(result, indent=2).encode())
    print(json.dumps(result))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise DeploymentError('usage_requires_nonsecret_scope_json')
        with open(sys.argv[1], encoding='utf-8') as handle:
            code = deploy(json.load(handle))
    except Exception as error:
        print(json.dumps({'success': False, 'state': 'preflight_or_tool_failure',
                          'error_type': type(error).__name__,
                          'error_code': str(error) if isinstance(error, DeploymentError) else 'unexpected_failure'}))
        code = 1
    sys.exit(code)
