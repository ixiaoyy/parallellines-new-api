#!/usr/bin/env python3
"""Materialize this fixed release from the official archive and ordered patches.

No downloads, credential reads, server operations or automatic deletion.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import zipfile

RELEASE = pathlib.Path(__file__).resolve().parent
REPO = RELEASE.parent.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(archive, destination, frontend=None):
    lock = json.loads((RELEASE / 'upstream.lock.json').read_text())
    if sha(archive) != lock['archive_sha256']:
        raise RuntimeError('Official source archive hash mismatch')
    for entry in lock['patches']:
        if sha(REPO / entry['file']) != entry['sha256']:
            raise RuntimeError('Release patch hash mismatch')
    if destination.exists():
        raise RuntimeError('Destination exists; inspect instead of overwriting')
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            name = pathlib.PurePosixPath(member.filename)
            if name.is_absolute() or '..' in name.parts or name.parts[0] != 'new-api-' + lock['commit']:
                raise RuntimeError('Unsafe source archive path')
        handle.extractall(destination)
    source = destination / ('new-api-' + lock['commit'])
    def git(*arguments):
        subprocess.run(['git', '-C', str(source), '-c', 'core.autocrlf=false', *arguments], check=True)
    git('init', '--quiet')
    for entry in lock['patches']:
        patch = str(REPO / entry['file'])
        git('apply', '--check', patch)
        git('apply', patch)
        git('apply', '--reverse', '--check', patch)
    profile = json.loads((REPO / 'patches/profile-sync-manifest.json').read_text())
    for name, entry in profile['files'].items():
        if sha(source / name) != entry['result_sha256']:
            raise RuntimeError('Profile source mismatch: ' + name)
    if frontend:
        evidence = json.loads((RELEASE / 'frontend-assets.json').read_text())
        for entry in evidence['files']:
            if sha(frontend / entry['file']) != entry['sha256']:
                raise RuntimeError('Frontend asset mismatch: ' + entry['file'])
        actual = {p.relative_to(frontend).as_posix() for p in frontend.rglob('*') if p.is_file()}
        if actual != {entry['file'] for entry in evidence['files']}:
            raise RuntimeError('Unexpected frontend asset set')
        shutil.copytree(frontend, source / 'web/dist')
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=pathlib.Path, default=REPO / '.build/upstream.zip')
    parser.add_argument('--destination', type=pathlib.Path, required=True)
    parser.add_argument('--frontend', type=pathlib.Path)
    args = parser.parse_args()
    print(materialize(args.archive.resolve(), args.destination.resolve(), args.frontend.resolve() if args.frontend else None))
