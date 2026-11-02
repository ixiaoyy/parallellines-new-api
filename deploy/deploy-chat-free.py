#!/usr/bin/env python3
"""维护本次 pkce.7 → pkce.8 免费 Chat 发布；不构建、不拉镜像、不恢复业务数据库。

在目标服务器运行：deploy-chat-free.py SCOPE.json prepare|install|enable|disable|health|recover。
必须先 prepare；install 保持免费门关闭，enable 只能在 Chat 隔离就绪后由发布负责人调用。
恢复顺序由负责人控制：disable、等待已获准请求排空、回退 Chat，最后按需 recover New API。
共享 CAS 路径及摘要由 scope 指定；不复制维护库，不读取密钥文件或生成管理凭据。
"""
import argparse
import copy
from contextlib import closing, contextmanager
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import subprocess
import sys
import time
import urllib.request

if os.name == 'posix':
    import fcntl
else:
    fcntl = None


FREE_FLAG = 'CHAT_OPENROUTER_FREE_ENABLED'
PRESERVED_FLAGS = (
    'MAIN_OAUTH_ACCOUNT_SYNC_ENABLED', 'MAIN_OAUTH_PROFILE_SYNC_ENABLED',
    'CHAT_OAUTH_RELAY_ENABLED', 'OPENAI_STANDARD_BILLING_ENABLED',
)
SAFE_ENV_NAMES = (*PRESERVED_FLAGS, FREE_FLAG, 'SQLITE_PATH')
TARGET = {
    'compose': '/opt/pl-official-candidate-20261030/compose.yaml',
    'project': 'pl-official-candidate-20261030', 'service': 'newapi',
    'container': 'pl-official-candidate-20261030-newapi-1',
}
DATA_DIRECTORY = '/data/candidates/pl-official-candidate-20261030/newapi'
REQUIRED = (
    'utils_path', 'utils_sha256', 'work_dir', 'compose', 'working_dir', 'compose_files',
    'env_files', 'project', 'service', 'container', 'database', 'status_url',
    'expected_image', 'expected_image_id', 'expected_binary_sha256', 'expected_version',
    'image', 'image_id', 'binary_sha256', 'version', 'new_build', 'preserved_flags',
)


class MaintenanceError(RuntimeError):
    """只携带固定错误码，不包含命令输出、Compose 内容或秘密值。"""


def require(condition, code):
    """条件不满足即停止，不重试配置写入或自动扩大修复范围。"""
    if not condition:
        raise MaintenanceError(code)


def public_path(value, under_data=False):
    """校验 scope 中的 Linux 绝对路径；该纯校验不读取文件。"""
    require(isinstance(value, str) and '\\' not in value and '\x00' not in value, 'invalid_path')
    path = PurePosixPath(value)
    require(path.is_absolute() and '..' not in path.parts and str(path) == value, 'invalid_path')
    require(not under_data or path.is_relative_to('/data'), 'data_path_required')
    return value


def safe_file_path(value):
    """操作前拒绝路径及父目录符号链接，避免恢复点或 Compose 被重定向。"""
    path = Path(value)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink_path_rejected')
    return path


def validate_scope(scope):
    """固定本次目标及版本对，返回仅含必要非敏感元数据的范围快照。"""
    require(isinstance(scope, dict) and all(key in scope for key in REQUIRED), 'scope_fields_missing')
    result = copy.deepcopy({key: scope[key] for key in REQUIRED})
    require(all(result[key] == value for key, value in TARGET.items()), 'wrong_deployment_target')
    require(result['expected_version'] == 'v0.13.2-pkce.7' and result['version'] == 'v0.13.2-pkce.8', 'wrong_release_pair')
    require(result['expected_image'] == 'parallellines-newapi:v0.13.2-pkce.7', 'wrong_baseline_image')
    for key in ('expected_image', 'image'):
        require(isinstance(result[key], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,240}', result[key]), 'invalid_image')
    require(result['image'] != result['expected_image'], 'new_image_must_differ')
    for key in ('expected_image_id', 'image_id'):
        require(isinstance(result[key], str) and re.fullmatch(r'sha256:[a-f0-9]{64}', result[key]), 'invalid_image_id')
    require(result['image_id'] != result['expected_image_id'], 'new_image_id_must_differ')
    for key in ('utils_sha256', 'expected_binary_sha256', 'binary_sha256'):
        require(isinstance(result[key], str) and re.fullmatch(r'[a-f0-9]{64}', result[key]), 'invalid_digest')
    for key in ('utils_path', 'work_dir', 'database'):
        public_path(result[key], True)
    public_path(result['compose'])
    public_path(result['working_dir'])
    require(result['database'] == DATA_DIRECTORY + '/new-api.db', 'explicit_database_binding_required')
    for key in ('compose_files', 'env_files'):
        require(isinstance(result[key], list) and all(isinstance(p, str) for p in result[key]), 'invalid_compose_inputs')
        for path in result[key]:
            public_path(path)
        require(len(set(result[key])) == len(result[key]), 'duplicate_compose_input')
    require(result['compose'] in result['compose_files'], 'target_compose_not_effective')
    require(result['status_url'] == 'http://127.0.0.1:13000/api/status', 'status_must_be_fixed_loopback')
    flags = result['preserved_flags']
    require(isinstance(flags, dict) and set(flags) == set(PRESERVED_FLAGS), 'preserved_flags_required')
    require(all(value in ('true', 'false') for value in flags.values()), 'invalid_preserved_flag')
    build = result['new_build']
    require(isinstance(build, dict) and set(build) <= {'context', 'dockerfile'} and 'context' in build, 'invalid_build_provenance')
    public_path(build['context'], True)
    if 'dockerfile' in build:
        require(isinstance(build['dockerfile'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', build['dockerfile']), 'invalid_dockerfile_name')
    return result


def scope_id(scope):
    """把本次非敏感范围固定到状态记录，拒绝换 scope 误用旧恢复点。"""
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def run(args, timeout=180, allow_failure=False):
    """有界运行固定维护命令；不打印可能展开秘密的 stdout/stderr。"""
    result = subprocess.run([str(arg) for arg in args], capture_output=True, timeout=timeout)
    if result.returncode and allow_failure:
        return None
    require(result.returncode == 0, 'maintenance_command_failed')
    return result.stdout.decode('utf-8').strip()


def load_utils(scope):
    """核对已上传共享 CAS 的摘要后导入，不复制或改写维护库。"""
    path = safe_file_path(scope['utils_path'])
    require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == scope['utils_sha256'], 'shared_cas_mismatch')
    spec = importlib.util.spec_from_file_location('chat_free_shared_cas', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sqlite_backup(database, destination):
    """从已核实的只读 SQLite 源生成一致私有快照；只写新备份，绝不恢复业务库。"""
    source_path = safe_file_path(database)
    require(source_path.is_file(), 'database_missing')
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    deadline = time.monotonic() + 30
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise MaintenanceError('database_backup_deadline')
    with closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True, timeout=5)) as source:
        source.execute('PRAGMA query_only=ON')
        with closing(sqlite3.connect(str(destination), timeout=5)) as target:
            source.backup(target, pages=256, sleep=0.05, progress=progress)


def verify_binding(service, metadata, database, runtime_env):
    """核对当前服务实际使用的 SQLite 及 bind mount，不猜测数据路径。"""
    require(service.get('environment', {}).get('SQLITE_PATH') == '/data/new-api.db', 'compose_sqlite_path_changed')
    require(runtime_env.get('SQLITE_PATH') == '/data/new-api.db', 'runtime_sqlite_path_changed')
    mounts = [m for m in metadata.get('mounts', []) if m.get('Destination') == '/data']
    require(len(mounts) == 1 and mounts[0].get('Type') == 'bind' and mounts[0].get('Source') == DATA_DIRECTORY, 'database_mount_changed')
    require(database == DATA_DIRECTORY + '/new-api.db', 'database_scope_changed')


class Maintenance:
    """只维护已预构建的新镜像与免费门；跨 Chat 发布顺序由唯一发布负责人控制。"""
    def __init__(self, scope, utils=None, runner=run, backup=sqlite_backup):
        self.scope = validate_scope(scope)
        self.utils = utils or load_utils(self.scope)
        self.run = runner
        self.backup = backup
        self.partial = False

    def compose(self, *args):
        """使用原项目、工作目录及有序输入，不展开 Compose 配置到日志。"""
        s = self.scope
        command = ['docker', 'compose', '--project-name', s['project'], '--project-directory', s['working_dir']]
        for path in s['env_files']:
            command += ['--env-file', path]
        for path in s['compose_files']:
            command += ['-f', path]
        return self.run(command + list(args), timeout=180)

    def document(self):
        """读取当前目标服务与精确字节摘要；共享 CAS 保留服务外所有字节。"""
        text = safe_file_path(self.scope['compose']).read_text(encoding='utf-8')
        document = self.utils.load_compose(text)
        service = document.get('services', {}).get('newapi')
        require(isinstance(service, dict) and isinstance(service.get('environment'), dict), 'invalid_target_service')
        require(all(str(service['environment'].get(k)).lower() == value for k, value in self.scope['preserved_flags'].items()), 'preserved_compose_flags_changed')
        return text, service, self.utils.service_hash(text, 'newapi')

    def metadata(self, required=True):
        """仅取容器身份、镜像、挂载及 Compose 标签，不读取完整环境或秘密。"""
        template = '{"id":{{json .Id}},"image_id":{{json .Image}},"image":{{json .Config.Image}},"running":{{json .State.Running}},"mounts":{{json .Mounts}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"working_dir":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},"config_files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}}}'
        output = self.run(['docker', 'inspect', '--format', template, self.scope['container']], timeout=30, allow_failure=not required)
        return json.loads(output) if output is not None else None

    def runtime_environment(self):
        """只读取四个既有布尔开关、免费门和 SQLite 路径；数据库连接串只检查类别不回显。"""
        self.run(['docker', 'exec', self.scope['container'], 'sh', '-c', 'test -z "$SQL_DSN" || test "$SQL_DSN" = local'], timeout=15)
        script = "printf '%s\\n' " + ' '.join('"$' + name + '"' for name in SAFE_ENV_NAMES)
        output = self.run(['docker', 'exec', self.scope['container'], 'sh', '-c', script], timeout=15)
        values = output.split('\n')
        require(len(values) == len(SAFE_ENV_NAMES), 'runtime_flag_shape_changed')
        return dict(zip(SAFE_ENV_NAMES, values))

    def recoverable_runtime(self):
        """允许失败重建后容器暂缺，但已有容器必须仍属于本次已核对项目和旧/新镜像。"""
        data = self.metadata(False)
        if data is not None:
            require(data['image_id'] in (self.scope['image_id'], self.scope['expected_image_id']), 'unexpected_recovery_image')
            require(data['project'] == self.scope['project'] and data['service'] == 'newapi', 'recovery_container_identity_changed')
            require(data['working_dir'] == self.scope['working_dir'] and data['config_files'].split(',') == self.scope['compose_files'], 'recovery_compose_inputs_changed')
        return data

    def verify_runtime(self, image, image_id, binary, version, gate):
        """核对实际镜像、二进制、既有开关和数据绑定；状态端点另有有界就绪等待。"""
        data = self.metadata()
        require(data['image'] == image and data['image_id'] == image_id, 'runtime_image_changed')
        require(data['project'] == self.scope['project'] and data['service'] == 'newapi', 'runtime_identity_changed')
        require(data['working_dir'] == self.scope['working_dir'] and data['config_files'].split(',') == self.scope['compose_files'], 'runtime_compose_inputs_changed')
        require(self.compose('ps', '-q', 'newapi') == data['id'], 'runtime_compose_container_changed')
        env = self.runtime_environment()
        require(all(env[k] == value for k, value in self.scope['preserved_flags'].items()), 'preserved_runtime_flags_changed')
        require(env[FREE_FLAG] == gate, 'runtime_free_gate_changed')
        _, service, _ = self.document()
        verify_binding(service, data, self.scope['database'], env)
        actual_binary = self.run(['docker', 'exec', self.scope['container'], 'sha256sum', '/new-api'], timeout=20).split()[0]
        require(actual_binary == binary, 'runtime_binary_changed')
        return {'version': version, 'image': image, 'image_id': image_id, 'free_gate': gate}

    def healthy(self, image, image_id, binary, version, gate):
        """只请求固定 loopback 状态接口，最长两分钟；不请求模型，不跟随重定向或代理。"""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            """状态检查不能跳转到其他地址。"""
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                """拒绝所有跳转，避免 loopback 检查变成外部请求。"""
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        deadline = time.monotonic() + 120
        while True:
            value = None
            try:
                with opener.open(self.scope['status_url'], timeout=5) as response:
                    raw = response.read(65537)
                    if len(raw) <= 65536:
                        value = json.loads(raw)
            except (OSError, ValueError):
                # 重建后的短暂连接/响应不可用允许有限等待；身份、配置和镜像错误不重试。
                pass
            if isinstance(value, dict) and value.get('success') is True and value.get('data', {}).get('version') == version:
                return self.verify_runtime(image, image_id, binary, version, gate)
            require(time.monotonic() < deadline, 'runtime_health_or_version_failed')
            time.sleep(2)

    def image_available(self, image, expected):
        """只检查预构建本地镜像，不构建或拉取任何镜像。"""
        require(self.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], timeout=20) == expected, 'prebuilt_image_changed')

    def build_provenance_available(self):
        """首次安装前核对已构建上下文仍存在；关闭免费门或恢复不依赖该构建目录。"""
        build = self.scope['new_build']
        context = safe_file_path(build['context'])
        require(context.is_dir(), 'build_context_missing')
        dockerfile = safe_file_path(str(context / build.get('dockerfile', 'Dockerfile')))
        require(dockerfile.is_file(), 'build_dockerfile_missing')

    def mutate(self, service, action):
        """返回仅含获准字段变化的服务副本，不改其他环境、挂载或配置值。"""
        result = copy.deepcopy(service)
        if action == 'install':
            require(result.get('image') == self.scope['expected_image'], 'baseline_compose_image_changed')
            result['image'] = self.scope['image']
            result['build'] = copy.deepcopy(self.scope['new_build'])
        else:
            require(result.get('image') == self.scope['image'], 'candidate_compose_image_changed')
        require(isinstance(result.get('environment'), dict), 'environment_mapping_required')
        result['environment'][FREE_FLAG] = 'true' if action == 'enable' else 'false'
        return result

    def state_matches(self, state, service_hash):
        """仅接受本次 scope 和已知当前/待写摘要；并发维护留下的其他状态不能恢复覆盖。"""
        require(state.get('format') == 1 and state.get('scope_id') == scope_id(self.scope), 'state_scope_changed')
        allowed = {state.get('service_hash')}
        pending = state.get('pending')
        if pending:
            allowed.update((pending['before_hash'], pending['after_hash']))
        require(all(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) for value in allowed), 'state_hash_invalid')
        require(service_hash in allowed, 'target_service_changed_concurrently')

    def transition(self, state, save, action, replacement):
        """持久记录本次前后摘要后调用共享 CAS；失败不自动重试或整文件恢复。"""
        text, _, current_hash = self.document()
        self.state_matches(state, current_hash)
        def update(service):
            service.clear()
            service.update(copy.deepcopy(replacement))
        intended = self.utils.patch_service(text, 'newapi', update)
        target_hash = self.utils.service_hash(intended, 'newapi')
        state['phase'] = action + '_pending'
        state['pending'] = {'before_hash': current_hash, 'after_hash': target_hash}
        save(state)
        self.partial = True
        backup_dir = Path(self.scope['work_dir']) / (action + '-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        changed = self.utils.cas_service_update(Path(self.scope['compose']), 'newapi', current_hash, update, backup_dir)
        require(changed['after_service_sha256'] == target_hash, 'unexpected_cas_result')
        state['service_hash'] = target_hash
        save(state)
        self.compose('config', '--quiet')
        require(self.compose('config', '--images', 'newapi') == replacement['image'], 'effective_compose_image_changed')
        self.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'newapi')

    def prepare(self, save):
        """第一次排他准备恢复点与一致备份；不改变运行服务或业务数据。"""
        self.compose('config', '--quiet')
        _, old, old_hash = self.document()
        require(old.get('image') == self.scope['expected_image'], 'baseline_compose_image_changed')
        require(self.compose('config', '--images', 'newapi') == self.scope['expected_image'], 'effective_baseline_image_changed')
        initial_gate = str(old['environment'].get(FREE_FLAG, '')).lower()
        require(initial_gate in ('', 'false'), 'baseline_free_gate_must_be_closed')
        self.healthy(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], initial_gate)
        self.build_provenance_available()
        self.image_available(self.scope['image'], self.scope['image_id'])
        state = {'format': 1, 'scope_id': scope_id(self.scope), 'phase': 'preparing', 'old_service': copy.deepcopy(old),
                 'old_service_hash': old_hash, 'old_gate': initial_gate, 'service_hash': old_hash, 'pending': None, 'ever_enabled': False}
        save(state)
        backup_path = Path(self.scope['work_dir']) / 'before-pkce8-new-api.db'
        self.backup(self.scope['database'], backup_path)
        _, _, current_hash = self.document()
        require(current_hash == old_hash, 'baseline_changed_during_backup')
        self.verify_runtime(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], initial_gate)
        state.update(phase='prepared', database_backup=str(backup_path))
        save(state)
        return {'ok': True, 'phase': 'prepared', 'database_backup': str(backup_path), 'database_restored': False}

    def operate(self, state, save, action):
        """按本次持久状态执行一项动作；恢复只回到本次捕获的 pkce.7，不回灌数据库。"""
        _, current, current_hash = self.document()
        self.state_matches(state, current_hash)
        self.compose('config', '--quiet')
        if action == 'health':
            old = current.get('image') == self.scope['expected_image']
            require(old or current.get('image') == self.scope['image'], 'unknown_runtime_target')
            prefix = 'expected_' if old else ''
            gate = state['old_gate'] if old else str(current['environment'].get(FREE_FLAG, '')).lower()
            return {'ok': True, 'phase': state['phase'], **self.healthy(self.scope[prefix+'image'], self.scope[prefix+'image_id'], self.scope[prefix+'binary_sha256'], self.scope[prefix+'version'], gate)}
        if action == 'recover':
            require(str(current['environment'].get(FREE_FLAG, '')).lower() != 'true', 'disable_free_gate_before_recovery')
            if state.get('ever_enabled'):
                require(time.time() >= state.get('drain_after', float('inf')), 'wait_for_free_requests_to_drain')
            self.image_available(self.scope['expected_image'], self.scope['expected_image_id'])
            data = self.recoverable_runtime()
            if data is not None:
                if data.get('running') and data['image_id'] == self.scope['image_id']:
                    require(self.runtime_environment()[FREE_FLAG] == 'false', 'running_free_gate_must_be_disabled')
            self.transition(state, save, action, state['old_service'])
            result = self.healthy(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], state['old_gate'])
            state.update(phase='recovered', pending=None)
        else:
            require(action in ('install', 'enable', 'disable'), 'unsupported_action')
            if action == 'install':
                require(state['phase'] == 'prepared', 'install_requires_prepared_state')
                self.healthy(self.scope['expected_image'], self.scope['expected_image_id'], self.scope['expected_binary_sha256'], self.scope['expected_version'], state['old_gate'])
                self.build_provenance_available()
            elif action == 'enable':
                require(state['phase'] in ('installed', 'disabled'), 'enable_requires_verified_install')
                self.healthy(self.scope['image'], self.scope['image_id'], self.scope['binary_sha256'], self.scope['version'], 'false')
                # 即使启用后的健康检查失败，也不能误认为免费门从未可能接收请求。
                state['ever_enabled'] = True
            elif state['phase'] in ('installed', 'disabled') and str(current['environment'].get(FREE_FLAG)).lower() == 'false':
                result = self.healthy(self.scope['image'], self.scope['image_id'], self.scope['binary_sha256'], self.scope['version'], 'false')
                return {'ok': True, 'action': action, 'phase': state['phase'], 'no_change': True,
                        'drain_after': state.get('drain_after'), 'database_restored': False, **result}
            else:
                self.recoverable_runtime()
            self.image_available(self.scope['image'], self.scope['image_id'])
            self.transition(state, save, action, self.mutate(current, action))
            gate = 'true' if action == 'enable' else 'false'
            result = self.healthy(self.scope['image'], self.scope['image_id'], self.scope['binary_sha256'], self.scope['version'], gate)
            if action == 'enable':
                state['ever_enabled'] = True
            elif action == 'disable' and state.get('ever_enabled'):
                state['drain_after'] = time.time() + 60
            state.update(phase={'install': 'installed', 'enable': 'enabled', 'disable': 'disabled'}[action], pending=None)
        save(state)
        self.partial = False
        return {'ok': True, 'action': action, 'phase': state['phase'], 'drain_after': state.get('drain_after'), 'database_restored': False, **result}

    @contextmanager
    def state_file(self, create):
        """仅锁住本次私有状态文件；不另建锁服务，忙时立即停止，首次创建不能覆盖。"""
        require(fcntl is not None, 'linux_server_required')
        work = safe_file_path(self.scope['work_dir'])
        work.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(stat.S_IMODE(work.stat().st_mode) == 0o700, 'work_directory_not_private')
        path = safe_file_path(str(work / 'state.json'))
        flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if create else 0)
        with os.fdopen(os.open(path, flags, 0o600), 'r+') as stream:
            require(stat.S_IMODE(os.fstat(stream.fileno()).st_mode) == 0o600, 'state_not_private')
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield stream
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def execute(self, action):
        """在独立 CLI 中持有状态锁执行动作；不输出私有状态、命令或配置正文。"""
        with self.state_file(action == 'prepare') as stream:
            def save(state):
                """在同一已锁定 inode 上保存本次状态，拒绝被外部替换的状态路径。"""
                opened, current = os.fstat(stream.fileno()), Path(self.scope['work_dir'], 'state.json').stat()
                require((opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino), 'state_file_replaced')
                stream.seek(0)
                stream.write(json.dumps(state, indent=2) + '\n')
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
            if action == 'prepare':
                return self.prepare(save)
            state = json.load(stream)
            return self.operate(state, save, action)


def main():
    """接收非敏感 scope 与单一维护动作，错误只输出固定原因及是否可能部分执行。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scope', type=Path)
    parser.add_argument('action', choices=['prepare', 'install', 'enable', 'disable', 'health', 'recover'])
    args = parser.parse_args()
    os.umask(0o077)
    maintenance = None
    try:
        maintenance = Maintenance(json.loads(args.scope.read_text(encoding='utf-8')))
        print(json.dumps(maintenance.execute(args.action)), flush=True)
    except Exception as error:
        print(json.dumps({'ok': False, 'action': args.action, 'state': 'stopped',
                          'partialOrUncertain': bool(maintenance and maintenance.partial),
                          'error_type': type(error).__name__,
                          'reason': str(error) if isinstance(error, MaintenanceError) else 'maintenance_stopped'}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
