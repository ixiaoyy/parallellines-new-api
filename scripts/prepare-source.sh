#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_commit=bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
source_sha=160ec2f227590195d1a91e14beb1b6eed02d446745ccf1afcb159c587e89069d
patch_sha=6ab7532fe7b69e6275272673cf1ad2d05540ba8b90c995b804b580429558938a
source_dir=".build/new-api-${source_commit}"
if [[ -e "$source_dir" ]]; then
  echo 'Source directory already exists; use a fresh checkout/build directory.' >&2
  exit 1
fi
mkdir -p .build
printf '%s  %s\n' "$patch_sha" patches/new-api-v0.13.2-pkce-oauth-relay.patch | sha256sum --check --status
if [[ ! -f .build/upstream.zip ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    "https://codeload.github.com/QuantumNous/new-api/zip/${source_commit}" \
    --output .build/upstream.zip
fi
printf '%s  %s\n' "$source_sha" .build/upstream.zip | sha256sum --check --status
unzip -q .build/upstream.zip -d .build
# Stop Git discovering this delivery repository: otherwise apply may silently
# skip upstream-relative paths when the source is below the repository root.
GIT_CEILING_DIRECTORIES="$PWD/.build" git -C "$source_dir" apply --check "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay.patch"
GIT_CEILING_DIRECTORIES="$PWD/.build" git -C "$source_dir" apply "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay.patch"
test -f "$source_dir/controller/oauth_pkce.go"
test -f "$source_dir/middleware/oauth_relay.go"
GIT_CEILING_DIRECTORIES="$PWD/.build" git -C "$source_dir" apply --reverse --check "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay.patch"
# Docker uses this directory as context, so copy the release filter into it.
cp .dockerignore "$source_dir/.dockerignore"
printf '%s\n' 'Prepared and verified the pinned source with the combined PKCE and Chat OAuth patch.'
