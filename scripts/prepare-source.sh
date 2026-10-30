#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_commit=bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
source_sha=160ec2f227590195d1a91e14beb1b6eed02d446745ccf1afcb159c587e89069d
patch_sha=b3df02767ff251f2fb23220e8798c721188b1780e9d346f3cea6fbfd1771bf6f
source_dir=".build/new-api-${source_commit}"
if [[ -e "$source_dir" ]]; then
  echo 'Source directory already exists; use a fresh checkout/build directory.' >&2
  exit 1
fi
mkdir -p .build
printf '%s  %s\n' "$patch_sha" patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch | sha256sum --check --status
if [[ ! -f .build/upstream.zip ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    "https://codeload.github.com/QuantumNous/new-api/zip/${source_commit}" \
    --output .build/upstream.zip
fi
printf '%s  %s\n' "$source_sha" .build/upstream.zip | sha256sum --check --status
unzip -q .build/upstream.zip -d .build
# Stop Git discovering this delivery repository: otherwise apply may silently
# skip upstream-relative paths when the source is below the repository root.
GIT_CEILING_DIRECTORIES="$PWD/.build" git -C "$source_dir" apply --check "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch"
GIT_CEILING_DIRECTORIES="$PWD/.build" git -C "$source_dir" apply "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch"
test -f "$source_dir/controller/oauth_pkce.go"
test -f "$source_dir/middleware/oauth_relay.go"
test -f "$source_dir/service/openai_standard_billing.go"
test -f "$source_dir/web/src/helpers/model-pricing-currency.js"
GIT_CEILING_DIRECTORIES="$PWD/.build" git -C "$source_dir" apply --reverse --check "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch"
# Docker uses this directory as context, so copy the release filter into it.
cp .dockerignore "$source_dir/.dockerignore"
printf '%s\n' 'Prepared and verified the pinned source with the combined PKCE, Chat OAuth and standard billing patch.'
