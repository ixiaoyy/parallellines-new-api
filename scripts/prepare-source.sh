#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_commit=bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
source_sha=160ec2f227590195d1a91e14beb1b6eed02d446745ccf1afcb159c587e89069d
patch_sha=1104f9fe8cdc4860dc7cf653d8de84d41f7f4201ad0eec5d7fec59ae7dbaa82f
source_dir=".build/new-api-${source_commit}"
if [[ -e "$source_dir" ]]; then
  echo 'Source directory already exists; use a fresh checkout/build directory.' >&2
  exit 1
fi
mkdir -p .build
printf '%s  %s\n' "$patch_sha" patches/new-api-v0.13.2-pkce.patch | sha256sum --check --status
if [[ ! -f .build/upstream.zip ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    "https://codeload.github.com/QuantumNous/new-api/zip/${source_commit}" \
    --output .build/upstream.zip
fi
printf '%s  %s\n' "$source_sha" .build/upstream.zip | sha256sum --check --status
unzip -q .build/upstream.zip -d .build
git -C "$source_dir" apply --check ../../patches/new-api-v0.13.2-pkce.patch
git -C "$source_dir" apply ../../patches/new-api-v0.13.2-pkce.patch
# Docker uses this directory as context, so copy the release filter into it.
cp .dockerignore "$source_dir/.dockerignore"
printf '%s\n' 'Prepared the pinned source and reviewed PKCE patch.'
