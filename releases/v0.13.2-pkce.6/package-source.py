"""从固定 pkce.5 源码归档及本提交的增量补丁生成完整对应源码，不运行离线验证。"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[2]


def main(base_archive, output):
    """输入旧版源码归档和全新输出路径；返回可用于构建/公开分发的源码归档。"""
    expected = json.loads((REPO / 'releases/v0.13.2-pkce.5/source-archive.json').read_text())['sha256']
    if hashlib.sha256(base_archive.read_bytes()).hexdigest() != expected or output.exists():
        raise RuntimeError('base_archive_mismatch_or_output_exists')
    stage = Path(tempfile.mkdtemp(prefix='cache-ttl-source-', dir=REPO / '.build'))
    source = stage / 'source'
    with tarfile.open(base_archive) as archive:
        for member in archive.getmembers():
            if not member.name.startswith('source/'):
                continue
            target = stage / member.name
            if not member.isfile() or not target.resolve().is_relative_to(source.resolve()):
                raise RuntimeError('unexpected_source_entry')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    # 这是部署构建所需的源码准备；不执行 --check、测试、lint 或 smoke。
    subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply',
                    str(REPO / 'patches/new-api-v0.13.2-cache-ttl-from-pkce5.patch')], cwd=source, check=True,
                   env={**os.environ, 'GIT_CEILING_DIRECTORIES': str(stage)})
    recipe = subprocess.check_output(['git', 'archive', '--format=tar', 'HEAD'], cwd=REPO)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                archive.add(path, arcname='source/' + path.relative_to(source).as_posix())
        with tarfile.open(fileobj=io.BytesIO(recipe)) as inputs:
            for member in inputs.getmembers():
                archive.addfile(member, inputs.extractfile(member) if member.isfile() else None)
    print(json.dumps({'file': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                      'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()}))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
