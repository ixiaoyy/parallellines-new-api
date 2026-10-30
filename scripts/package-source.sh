#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_commit=bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
source_sha=160ec2f227590195d1a91e14beb1b6eed02d446745ccf1afcb159c587e89069d
patch_sha=1104f9fe8cdc4860dc7cf653d8de84d41f7f4201ad0eec5d7fec59ae7dbaa82f
[[ -f .build/upstream.zip ]] || { echo 'Run scripts/prepare-source.sh first' >&2; exit 1; }
printf '%s  %s\n' "$source_sha" .build/upstream.zip | sha256sum --check --status
printf '%s  %s\n' "$patch_sha" patches/new-api-v0.13.2-pkce.patch | sha256sum --check --status
mkdir -p dist
# Recreate from verified inputs, never package the working/build/runtime tree.
staging=$(mktemp -d .build/source-release.XXXXXX)
unzip -q .build/upstream.zip -d "$staging"
source_dir="$staging/new-api-$source_commit"
git -C "$source_dir" apply --check "$PWD/patches/new-api-v0.13.2-pkce.patch"
git -C "$source_dir" apply "$PWD/patches/new-api-v0.13.2-pkce.patch"
cp .dockerignore "$source_dir/.dockerignore"
tar --transform="s|^${source_dir}|source|" \
  -czf dist/new-api-v0.13.2-pkce.1-corresponding-source.tar.gz \
  "$source_dir" patches/new-api-v0.13.2-pkce.patch \
  scripts/prepare-source.sh scripts/build-local.sh scripts/package-source.sh \
  Dockerfile Dockerfile.runtime .dockerignore upstream.lock.json LICENSE NOTICE.md \
  README.md docs/OPERATIONS.md compose.yaml .env.example deploy/runtime.env.example \
  deploy/nginx-api.conf
sha256sum dist/new-api-v0.13.2-pkce.1-corresponding-source.tar.gz \
  > dist/SOURCE-SHA256SUMS
printf '%s\n' 'Publish the source archive and its checksum with the exact deployed release.'
