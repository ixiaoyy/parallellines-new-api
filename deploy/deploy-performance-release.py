#!/usr/bin/env python3
"""pkce.8 → pkce.9 image-only 发布/恢复；不改环境，不构建镜像，不请求 OAuth/模型。"""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import re

SPEC = importlib.util.spec_from_file_location('pkce8_deploy_base', Path(__file__).with_name('deploy-chat-free.py'))
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
FLAGS = (*BASE.PRESERVED_FLAGS, BASE.FREE_FLAG)


def validate_scope(scope):
    """固定原产品、版本对与已预检恢复点；resolved 开关可为空，不能为升级补写默认值。"""
    BASE.require(isinstance(scope, dict) and all(key in scope for key in (*BASE.REQUIRED, 'source_revision')), 'scope_fields_missing')
    value = copy.deepcopy({key: scope[key] for key in (*BASE.REQUIRED, 'source_revision')})
    BASE.require(all(value[key] == expected for key, expected in BASE.TARGET.items()), 'wrong_deployment_target')
    BASE.require(value['expected_version'] == 'v0.13.2-pkce.8' and value['version'] == 'v0.13.2-pkce.9', 'wrong_release_pair')
    BASE.require(value['image'] == 'parallellines-newapi:v0.13.2-pkce.9' and value['expected_image'] != value['image'], 'wrong_release_image')
    BASE.require(isinstance(value['source_revision'], str) and re.fullmatch('[0-9a-f]{40}', value['source_revision']), 'invalid_source_revision')
    for key in ('expected_image', 'image'):
        BASE.require(isinstance(value[key], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,240}', value[key]), 'invalid_image')
    for key in ('expected_image_id', 'image_id'):
        BASE.require(isinstance(value[key], str) and re.fullmatch('sha256:[0-9a-f]{64}', value[key]), 'invalid_image_id')
    BASE.require(value['expected_image_id'] != value['image_id'], 'new_image_id_must_differ')
    for key in ('utils_sha256', 'expected_binary_sha256', 'binary_sha256'):
        BASE.require(isinstance(value[key], str) and re.fullmatch('[0-9a-f]{64}', value[key]), 'invalid_digest')
    for key in ('utils_path', 'work_dir', 'database'):
        BASE.public_path(value[key], True)
    BASE.public_path(value['compose'])
    BASE.public_path(value['working_dir'])
    BASE.require(value['database'] == BASE.DATA_DIRECTORY + '/new-api.db', 'explicit_database_binding_required')
    for key in ('compose_files', 'env_files'):
        BASE.require(isinstance(value[key], list) and all(isinstance(path, str) for path in value[key]), 'invalid_compose_inputs')
        for path in value[key]:
            BASE.public_path(path)
        BASE.require(len(set(value[key])) == len(value[key]), 'duplicate_compose_input')
    BASE.require(value['compose'] in value['compose_files'], 'target_compose_not_effective')
    BASE.require(value['status_url'] == 'http://127.0.0.1:13000/api/status', 'status_must_be_fixed_loopback')
    BASE.require(isinstance(value['preserved_flags'], dict) and set(value['preserved_flags']) == set(FLAGS), 'all_runtime_flags_required')
    BASE.require(all(flag in ('', 'true', 'false') for flag in value['preserved_flags'].values()), 'invalid_preserved_flag')
    build = value['new_build']
    BASE.require(isinstance(build, dict) and set(build) <= {'context', 'dockerfile'} and 'context' in build, 'invalid_build_provenance')
    BASE.public_path(build['context'], True)
    BASE.require(isinstance(build.get('dockerfile', 'Dockerfile'), str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', build.get('dockerfile', 'Dockerfile')), 'invalid_dockerfile_name')
    return value


class PerformanceRelease(BASE.Maintenance):
    """复用既有私有状态锁、CAS、镜像/数据绑定和健康底座；不复用免费门切换动作。"""
    def __init__(self, scope, utils=None, runner=BASE.run, backup=BASE.sqlite_backup):
        self.scope = validate_scope(scope)
        self.utils = utils or BASE.load_utils(self.scope)
        self.run = runner
        self.backup = backup
        self.partial = False

    def document(self):
        """按原字节摘要读取目标服务；开关由原配置持有，不要求从 env_file 移入 environment。"""
        text = BASE.safe_file_path(self.scope['compose']).read_text(encoding='utf-8')
        service = self.utils.load_compose(text).get('services', {}).get('newapi')
        BASE.require(isinstance(service, dict), 'invalid_target_service')
        return text, service, self.utils.service_hash(text, 'newapi')

    def mutate(self, service):
        """唯一允许的新配置变化是 image/build，其余环境、挂载、依赖和资源限制逐值保留。"""
        BASE.require(service.get('image') == self.scope['expected_image'], 'baseline_compose_image_changed')
        changed = copy.deepcopy(service)
        changed['image'] = self.scope['image']
        changed['build'] = copy.deepcopy(self.scope['new_build'])
        return changed

    def image_available(self, image, expected):
        """使用预构建不可变镜像；新版本还须绑定本次已提交 source revision，旧恢复镜像不加新前置。"""
        super().image_available(image, expected)
        if image == self.scope['image']:
            template = '{"version":{{json (index .Config.Labels "org.opencontainers.image.version")}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}}}'
            labels = json.loads(self.run(['docker', 'image', 'inspect', '--format', template, image], timeout=20))
            BASE.require(labels == {'version': self.scope['version'], 'revision': self.scope['source_revision']}, 'release_image_source_mismatch')

    def prepare(self, save):
        """保存可用 pkce.8 镜像/服务定义与一致备份；不改免费门、数据库或运行服务。"""
        self.compose('config', '--quiet')
        _, old, old_hash = self.document()
        BASE.require(old.get('image') == self.scope['expected_image'], 'baseline_compose_image_changed')
        BASE.require(self.compose('config', '--images', 'newapi') == self.scope['expected_image'], 'effective_baseline_image_changed')
        gate = self.scope['preserved_flags'][BASE.FREE_FLAG]
        self.healthy(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], gate)
        self.image_available(self.scope['expected_image'], self.scope['expected_image_id'])
        self.image_available(self.scope['image'], self.scope['image_id'])
        self.build_provenance_available()
        state = {'format': 1, 'scope_id': BASE.scope_id(self.scope), 'phase': 'preparing', 'old_service': copy.deepcopy(old), 'old_service_hash': old_hash, 'service_hash': old_hash, 'pending': None}
        save(state)
        backup = Path(self.scope['work_dir']) / 'before-pkce9-new-api.db'
        self.backup(self.scope['database'], backup)
        _, _, current_hash = self.document()
        BASE.require(current_hash == old_hash, 'baseline_changed_during_backup')
        self.verify_runtime(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], gate)
        state.update(phase='prepared', database_backup=str(backup))
        save(state)
        return {'ok': True, 'phase': 'prepared', 'database_backup': str(backup), 'database_restored': False, 'environment_changed': False}

    def operate(self, state, save, action):
        """仅安装、原状态健康核验或回原镜像；失败留 pending，不自动恢复数据库或改功能门。"""
        _, current, current_hash = self.document()
        self.state_matches(state, current_hash)
        self.compose('config', '--quiet')
        BASE.require(current.get('image') in (self.scope['expected_image'], self.scope['image']), 'unknown_runtime_target')
        gate = self.scope['preserved_flags'][BASE.FREE_FLAG]
        if action == 'health':
            prefix = 'expected_' if current['image'] == self.scope['expected_image'] else ''
            return {'ok': True, 'phase': state['phase'], **self.healthy(self.scope[prefix+'image'], self.scope[prefix+'image_id'], self.scope[prefix+'binary_sha256'], self.scope[prefix+'version'], gate)}
        if action == 'install':
            BASE.require(state['phase'] == 'prepared', 'install_requires_prepared_state')
            self.healthy(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], gate)
            self.image_available(self.scope['expected_image'], self.scope['expected_image_id'])
            self.image_available(self.scope['image'], self.scope['image_id'])
            self.build_provenance_available()
            self.transition(state, save, action, self.mutate(current))
            result = self.healthy(self.scope['image'], self.scope['image_id'], self.scope['binary_sha256'], self.scope['version'], gate)
            state.update(phase='installed', pending=None)
        else:
            BASE.require(action == 'recover', 'unsupported_action')
            self.image_available(self.scope['expected_image'], self.scope['expected_image_id'])
            self.recoverable_runtime()
            self.transition(state, save, action, state['old_service'])
            result = self.healthy(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], gate)
            state.update(phase='recovered', pending=None)
        save(state)
        self.partial = False
        return {'ok': True, 'phase': state['phase'], 'database_restored': False, 'environment_changed': False, **result}


def main():
    """Linux 私有 scope/state 入口；只输出固定结果，不输出配置、秘密或原始异常正文。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scope', type=Path)
    parser.add_argument('action', choices=['prepare', 'install', 'health', 'recover'])
    args = parser.parse_args()
    os.umask(0o077)
    release = None
    try:
        release = PerformanceRelease(json.loads(args.scope.read_text(encoding='utf-8')))
        print(json.dumps(release.execute(args.action)), flush=True)
    except Exception as error:
        print(json.dumps({'ok': False, 'action': args.action, 'partialOrUncertain': bool(release and release.partial), 'error_type': type(error).__name__, 'reason': str(error) if isinstance(error, BASE.MaintenanceError) else 'release_stopped'}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
