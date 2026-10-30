#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_commit=bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
source_sha=160ec2f227590195d1a91e14beb1b6eed02d446745ccf1afcb159c587e89069d
patch_sha=b3df02767ff251f2fb23220e8798c721188b1780e9d346f3cea6fbfd1771bf6f
[[ -f .build/upstream.zip ]] || { echo 'Run scripts/prepare-source.sh first' >&2; exit 1; }
printf '%s  %s\n' "$source_sha" .build/upstream.zip | sha256sum --check --status
printf '%s  %s\n' "$patch_sha" patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch | sha256sum --check --status
mkdir -p dist
# Recreate from verified inputs, never package the working/build/runtime tree.
staging=$(mktemp -d .build/source-release.XXXXXX)
unzip -q .build/upstream.zip -d "$staging"
source_dir="$staging/new-api-$source_commit"
GIT_CEILING_DIRECTORIES="$PWD/$staging" git -C "$source_dir" apply --check "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch"
GIT_CEILING_DIRECTORIES="$PWD/$staging" git -C "$source_dir" apply "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch"
test -f "$source_dir/controller/oauth_pkce.go"
test -f "$source_dir/middleware/oauth_relay.go"
test -f "$source_dir/service/openai_standard_billing.go"
test -f "$source_dir/web/src/helpers/model-pricing-currency.js"
GIT_CEILING_DIRECTORIES="$PWD/$staging" git -C "$source_dir" apply --reverse --check "$PWD/patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch"
cp .dockerignore "$source_dir/.dockerignore"
tar --transform="s|^${source_dir}|source|" \
  -czf dist/new-api-v0.13.2-pkce.3-corresponding-source.tar.gz \
  "$source_dir" patches/new-api-v0.13.2-pkce-oauth-relay-billing.patch \
  scripts/prepare-source.sh scripts/build-local.sh scripts/package-source.sh \
  scripts/guard-legacy-rollback.py scripts/test_guard_legacy_rollback.py \
  Dockerfile Dockerfile.runtime .dockerignore upstream.lock.json LICENSE NOTICE.md \
  README.md docs/OPERATIONS.md docs/OAUTH-RELAY.md compose.yaml .env.example deploy/runtime.env.example \
  deploy/nginx-api.conf docs/STANDARD-BILLING-RELEASE.md \
  deploy/deploy-personal-relay.py deploy/test_deploy_personal_relay.py \
  deploy/deploy-standard-billing.py deploy/test_deploy_standard_billing.py
sha256sum dist/new-api-v0.13.2-pkce.3-corresponding-source.tar.gz \
  > dist/SOURCE-SHA256SUMS
printf '%s\n' 'Publish the source archive and its checksum with the exact deployed release.'
