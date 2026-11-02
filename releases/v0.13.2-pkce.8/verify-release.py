"""离线核对免费 Chat 增量的生产/验证补丁和旧契约保留；不执行 Go、数据库或模型请求。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


RELEASE = Path(__file__).resolve().parent
REPO = RELEASE.parent.parent


def digest(path):
    """返回发布文件摘要，仅用于核对已固定的归档、补丁和源码完整性。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(base_archive, destination):
    """在全新目录分别准备生产和测试源码，返回真实已完成检查及明确未运行项。"""
    if destination.exists():
        raise RuntimeError('verification_destination_exists')
    lock = json.loads((RELEASE / 'upstream.lock.json').read_text(encoding='utf-8'))
    manifest = json.loads((REPO / 'patches/free-chat-manifest.json').read_text(encoding='utf-8'))
    spec = importlib.util.spec_from_file_location('pkce8_prepare', RELEASE / 'prepare-source.py')
    preparation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparation)
    destination.mkdir(parents=True)
    production = preparation.prepare(base_archive, destination / 'production', False)
    with_tests = preparation.prepare(base_archive, destination / 'verification', True)

    # 测试补丁不得改变任何已验明的生产文件，两种准备方式必须得到同一份业务代码。
    for entry in manifest['files']:
        if digest(production / entry['path']) != entry['result_sha256']:
            raise RuntimeError('production_manifest_mismatch: ' + entry['path'])
        if (production / entry['path']).read_bytes() != (with_tests / entry['path']).read_bytes():
            raise RuntimeError('verification_changed_production: ' + entry['path'])
    for entry in manifest['preserved_files']:
        for source in (production, with_tests):
            if digest(source / entry['path']) != entry['sha256']:
                raise RuntimeError('preserved_contract_changed: ' + entry['path'])

    # 持久凭据常量及全部旧凭据函数保持原字节，不能用扩白名单恢复或重发撤销凭据。
    for source in (production, with_tests):
        text = (source / 'model/oauth_relay.go').read_text(encoding='utf-8')
        if manifest['persistent_model_limits_line'] not in text.splitlines():
            raise RuntimeError('persistent_model_limits_changed')
        tail = text[text.index('func userManagedTokens('):]
        if hashlib.sha256(tail.encode('utf-8')).hexdigest() != manifest['credential_implementation_sha256']:
            raise RuntimeError('persistent_credential_implementation_changed')
    for entry in manifest['verification_files']:
        if digest(with_tests / entry['path']) != entry['sha256']:
            raise RuntimeError('verification_file_mismatch: ' + entry['path'])
        if not entry['path'].endswith('_test.go'):
            raise RuntimeError('verification_patch_contains_non_test_file: ' + entry['path'])
        if entry['added'] and (production / entry['path']).exists():
            raise RuntimeError('verification_file_entered_production_patch: ' + entry['path'])
        if not entry['added'] and not (production / entry['path']).is_file():
            raise RuntimeError('existing_verification_file_missing: ' + entry['path'])

    # 失败恢复入口同样核对：错误基线与已有目标都在写源码前拒绝，不覆盖已准备成果。
    invalid_archive = destination / 'not-the-approved-archive'
    invalid_archive.write_bytes(b'not an approved source archive')
    try:
        preparation.prepare(invalid_archive, destination / 'rejected-base', False)
    except RuntimeError:
        if (destination / 'rejected-base').exists():
            raise RuntimeError('invalid_base_left_source_output')
    else:
        raise RuntimeError('invalid_base_was_accepted')
    try:
        preparation.prepare(base_archive, production.parent, False)
    except RuntimeError:
        pass
    else:
        raise RuntimeError('existing_destination_was_overwritten')

    result = {
        'application_version': lock['application_version'],
        'source_preparation': 'production and verification patches applied and matched manifests',
        'production_files': len(manifest['files']),
        'verification_files': len(manifest['verification_files']),
        'preserved_contract_files': len(manifest['preserved_files']),
        'persistent_credentials_unchanged': True,
        'invalid_base_rejected_without_output': True,
        'existing_destination_rejected': True,
        'go_compile_run': False,
        'go_tests_run': False,
        'real_model_calls': False,
        'database_or_remote_calls': False,
        'deployment_performed': False,
        'production_source': str(production),
        'verification_source': str(with_tests),
    }
    (destination / 'check-results.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-archive', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.base_archive.resolve(), args.destination.resolve()), ensure_ascii=False, indent=2))
