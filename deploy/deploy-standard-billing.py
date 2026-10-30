#!/usr/bin/env python3
"""Forward-only pkce.2 -> pkce.3 billing upgrade; never restore DB or old binary.

Uses the same nonsecret scope schema as deploy-personal-relay.py. Keep both
scripts together. No model request, price-option write, role or balance mutation.
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
POLICY_ENV = 'OPENAI_STANDARD_BILLING_ENABLED'
OLD_IMAGE = 'parallellines-newapi:v0.13.2-pkce.2'
NEW_IMAGE = 'parallellines-newapi:v0.13.2-pkce.3'
VERSION = 'v0.13.2-pkce.3'


def render_compose(original, expected_image, relay_enabled=True):
    """Keep policy on even during recovery; update only exact New API scalars."""
    original_config = yaml.safe_load(original)
    old_env = original_config['services']['newapi'].get('environment', {})
    if str(old_env.get('CHAT_OAUTH_RELAY_ENABLED')).lower() not in ('true', 'false'):
        raise DeploymentError('existing_personal_relay_flag_missing')
    if POLICY_ENV in old_env and str(old_env[POLICY_ENV]).lower() not in ('false', 'true'):
        raise DeploymentError('unexpected_existing_policy_flag')
    text = base.render_compose(original, expected_image, NEW_IMAGE, relay_enabled).decode('utf-8')
    node = yaml.compose(text)
    api = base.mapping_value(base.mapping_value(node, 'services'), 'newapi')
    env = base.mapping_value(api, 'environment')
    matches = [value for key, value in env.value if key.value == POLICY_ENV]
    if len(matches) > 1:
        raise DeploymentError('duplicate_policy_flag')
    if matches:
        value = matches[0]
        if not isinstance(value, yaml.ScalarNode):
            raise DeploymentError('invalid_policy_flag')
        text = text[:value.start_mark.index] + '"true"' + text[value.end_mark.index:]
    else:
        insertion = text.rfind('\n', 0, env.end_mark.index) + 1
        if env.end_mark.index == len(text) and not text.endswith('\n'):
            insertion = len(text)
        newline = '\r\n' if '\r\n' in text else '\n'
        prefix = newline if insertion == len(text) and not text.endswith('\n') else ''
        indent = ' ' * env.value[0][0].start_mark.column
        text = text[:insertion] + prefix + indent + POLICY_ENV + ': "true"' + newline + text[insertion:]
    expected = original_config
    expected['services']['newapi']['image'] = NEW_IMAGE
    expected['services']['newapi']['environment']['CHAT_OAUTH_RELAY_ENABLED'] = 'true' if relay_enabled else 'false'
    expected['services']['newapi']['environment'][POLICY_ENV] = 'true'
    if yaml.safe_load(text) != expected:
        raise DeploymentError('unintended_compose_change')
    return text.encode('utf-8')


def validate_scope(scope):
    base.validate_scope(scope)
    if (scope['expected_image'], scope['image'], scope['version']) != (OLD_IMAGE, NEW_IMAGE, VERSION):
        raise DeploymentError('only_reviewed_pkce2_to_pkce3_upgrade_allowed')


def verify_runtime(scope, relay_enabled):
    image = base.run(['docker', 'inspect', '--format', '{{.Config.Image}}', scope['container']]).strip()
    if image != NEW_IMAGE:
        raise DeploymentError('new_billing_image_not_active')
    # Test only known nonsensitive flags; never print the container environment.
    expected_relay = 'true' if relay_enabled else 'false'
    script = ('test "$OPENAI_STANDARD_BILLING_ENABLED" = true && '
              'test "$CHAT_OAUTH_RELAY_ENABLED" = ' + expected_relay + ' && '
              'test "$CHANNEL_TEST_FREQUENCY" = 0 && '
              'test "$GENERATE_DEFAULT_TOKEN" = false && '
              'test "$CUSTOM_OAUTH_PKCE_PROVIDERS" = pingxingxian')
    base.run(['docker', 'exec', scope['container'], 'sh', '-c', script])


def isolated_smoke():
    """Boot the actual policy flag without a network, account, or persistent data."""
    smoke = base.run(['docker', 'run', '-d', '--network=none', '--read-only', '--memory=384m', '--cpus=0.5',
                      '--tmpfs', '/data:rw,noexec,nosuid,size=64m', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                      '-e', 'SQLITE_PATH=/data/smoke.db', '-e', 'GENERATE_DEFAULT_TOKEN=false',
                      '-e', 'CHANNEL_TEST_FREQUENCY=0', '-e', 'CHAT_OAUTH_RELAY_ENABLED=false',
                      '-e', POLICY_ENV + '=true', NEW_IMAGE]).strip()
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
            raise DeploymentError('isolated_policy_smoke_failed')
        setup = json.loads(base.run(['docker', 'exec', smoke, 'wget', '-qO-', 'http://127.0.0.1:3000/api/setup']))
        if setup.get('data', {}).get('root_init') is not False:
            raise DeploymentError('unexpected_smoke_account')
    finally:
        base.run(['docker', 'rm', '-f', smoke])


def recover(scope, original, proposed, compose_command):
    """Always stay on pkce.3; historical billing rows and hidden keys are retained."""
    try:
        compose_command('stop', 'newapi')
    except Exception:
        return 'pending_recovery_stop_failed'
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
        return 'pending_recovery_pkce3_policy_retained_relay_disabled'
    except Exception:
        try:
            compose_command('stop', 'newapi')
        except Exception:
            pass
        return 'pending_recovery_pkce3_only_operator_required'


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
    original_config = yaml.safe_load(original)
    env = original_config['services']['newapi']['environment']
    if str(env.get('CHAT_OAUTH_RELAY_ENABLED')).lower() != 'true':
        raise DeploymentError('expected_existing_relay_enabled')
    if str(env.get(POLICY_ENV, 'false')).lower() != 'false':
        raise DeploymentError('policy_already_configured_inspect_before_retry')
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
    # A distinct immutable build must not silently replace a prior interrupted tag.
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
              'price_options_written': False, 'balances_changed_by_deployer': False,
              'policy_env': POLICY_ENV, 'policy_basis': 'OpenAI public standard schedule; site quota policy, not actual invoice guarantee'}
    if compose_path.read_bytes() != original:
        raise DeploymentError('compose_changed_during_build')
    base.save_private(receipt, json.dumps({**result, 'state': 'activation_pending'}).encode())
    try:
        compose_command('stop', 'newapi')
        database = base.data_path(scope['database'])
        if not database.is_file():
            raise DeploymentError('database_missing')
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(str(backup / 'new-api.db'))) as target:
                source.backup(target)
        (backup / 'new-api.db').chmod(0o600)
        if compose_path.read_bytes() != original:
            raise DeploymentError('compose_changed_during_backup')
        base.save_private(compose_path, proposed)
        compose_command('config', '--quiet')
        compose_command('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'newapi')
        base.wait_health(scope)
        verify_runtime(scope, True)
        result.update(success=True, state='healthy_standard_billing_enabled')
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
