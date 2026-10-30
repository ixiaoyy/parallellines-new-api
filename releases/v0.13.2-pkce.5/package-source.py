#!/usr/bin/env python3
"""Create corresponding source from verified public inputs, never runtime state."""
import gzip
import hashlib
import importlib.util
import io
import json
import pathlib
import tarfile
import tempfile

RELEASE = pathlib.Path(__file__).resolve().parent
REPO = RELEASE.parent.parent
SPEC = importlib.util.spec_from_file_location('release_source', RELEASE / 'prepare-source.py')
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


def source_files(source):
    return {p.relative_to(source).as_posix(): p for p in source.rglob('*')
            if p.is_file() and '.git' not in p.relative_to(source).parts
            and not p.relative_to(source).as_posix().startswith('web/dist/')}


def main():
    stage = pathlib.Path(tempfile.mkdtemp(prefix='pkce5-source-', dir=REPO / '.build')) / 'verified'
    source = prepare.materialize(REPO / '.build/upstream.zip', stage)
    files = source_files(source)
    frozen = source_files(REPO / '.build/pkce5-frozen' / source.name)
    manifest = [{'file': name, 'sha256': prepare.sha(path), 'bytes': path.stat().st_size}
                for name, path in sorted(files.items())]
    if files.keys() != frozen.keys() or any(prepare.sha(path) != prepare.sha(frozen[name]) for name, path in files.items()):
        raise RuntimeError('Reconstructed source differs from the built frozen source')
    (RELEASE / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    recipe_names = [
        'LICENSE', 'NOTICE.md', '.dockerignore', 'Dockerfile.runtime',
        'patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch',
        'patches/new-api-v0.13.2-profile-sync-from-pkce3.patch',
        'patches/new-api-v0.13.2-deleted-session-from-pkce4.patch',
        'patches/deleted-session-manifest.json',
        'patches/profile-sync-manifest.json', 'docs/PROFILE-SYNC-RELEASE.md',
        'docs/STANDARD-BILLING-RELEASE.md', 'deploy/runtime.env.example',
        'deploy/deploy-deleted-session.py', 'deploy/test_deploy_deleted_session.py',
        'deploy/deploy-personal-relay.py', 'deploy/test_deploy_personal_relay.py',
        'releases/v0.13.2-pkce.5/upstream.lock.json',
        'releases/v0.13.2-pkce.5/base-pkce4.lock.json',
        'releases/v0.13.2-pkce.5/README.md', 'releases/v0.13.2-pkce.5/build.sh',
        'releases/v0.13.2-pkce.5/prepare-source.py', 'releases/v0.13.2-pkce.5/package-source.py',
        'releases/v0.13.2-pkce.5/source-manifest.json',
        'releases/v0.13.2-pkce.5/frontend-assets.json',
        'releases/v0.13.2-pkce.5/artifact-checksums.json',
        'releases/v0.13.2-pkce.5/make-delta.mjs',
        'releases/v0.13.2-pkce.5/apply-delta.py',
        'releases/v0.13.2-pkce.5/test_delta.py',
    ]
    entries = [('source/' + name, path) for name, path in files.items()]
    entries += [(name, REPO / name) for name in recipe_names]
    output = REPO / 'dist/pkce5/new-api-v0.13.2-pkce.5-corresponding-source.tar.gz'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RuntimeError('Source archive exists; inspect before retry')
    with output.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as archive:
                for name, path in sorted(entries):
                    content = path.read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    info.mode = 0o755 if name.endswith('.sh') else 0o644
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(content))
    with tarfile.open(output, mode='r:gz') as archive:
        members = archive.getmembers()
        if {m.name for m in members} != {name for name, _ in entries}:
            raise RuntimeError('Source archive inventory mismatch')
        expected = dict(entries)
        for member in members:
            if hashlib.sha256(archive.extractfile(member).read()).hexdigest() != prepare.sha(expected[member.name]):
                raise RuntimeError('Source archive file hash mismatch')
    evidence = {'file': output.relative_to(REPO).as_posix(), 'bytes': output.stat().st_size,
                'sha256': prepare.sha(output), 'source_files': len(files),
                'archive_files': len(entries), 'reconstructed_source_matches_binary_snapshot': True,
                'all_archive_entries_verified': True}
    (RELEASE / 'source-archive.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
