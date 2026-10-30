"""Apply the optional profile increment after prepare-source.sh's pkce.3 baseline."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
PATCH = REPOSITORY / 'patches/new-api-v0.13.2-profile-sync-from-pkce3.patch'
PATCH_SHA256 = '77921fcb4bb432fe2acc32fdeb27ac3bfc5834e06ce132620118075fff0d8054'


def main():
    source = Path(sys.argv[1]).resolve(strict=True)
    if not source.is_dir():
        raise SystemExit('Prepared source must be a directory')
    if hashlib.sha256(PATCH.read_bytes()).hexdigest() != PATCH_SHA256:
        raise SystemExit('Profile patch hash mismatch')
    manifest = json.loads((REPOSITORY / 'patches/profile-sync-manifest.json').read_text(encoding='utf-8'))
    for relative, hashes in manifest['files'].items():
        target = source / relative
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise SystemExit('Unexpected source path')
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        if actual != hashes['base_sha256']:
            raise SystemExit('Profile baseline mismatch: ' + relative)
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(source.parent)}
    git = ['git', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false']
    subprocess.run(git + ['apply', '--check', str(PATCH)], cwd=source, env=env, check=True)
    subprocess.run(git + ['apply', str(PATCH)], cwd=source, env=env, check=True)
    for relative, hashes in manifest['files'].items():
        if hashlib.sha256((source / relative).read_bytes()).hexdigest() != hashes['result_sha256']:
            raise SystemExit('Profile result mismatch: ' + relative)
    print('Profile increment applied and all six source hashes verified')


if __name__ == '__main__':
    main()
