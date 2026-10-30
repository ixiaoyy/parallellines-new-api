#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(bun --version)" == '1.4.4' ]] || { echo 'Bun 1.4.4 required' >&2; exit 1; }
[[ "$(go env GOVERSION)" == 'go1.26.1' ]] || { echo 'Go 1.26.1 required' >&2; exit 1; }
source_dir=${SOURCE_DIR:-.build/new-api-bee339d279ccecbf8c8a89e14ddbbd902f78bd5d}
[[ -d "$source_dir" ]] || { echo 'Run scripts/prepare-source.sh first' >&2; exit 1; }
repo_root="$PWD"
mkdir -p dist
(
  cd "$source_dir/web"
  bun install --frozen-lockfile
  DISABLE_ESLINT_PLUGIN=true VITE_REACT_APP_VERSION=v0.13.2-pkce.1 bun run build
)
(
  cd "$source_dir"
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOEXPERIMENT=greenteagc \
    go build -buildvcs=false \
    -ldflags '-s -w -X github.com/QuantumNous/new-api/common.Version=v0.13.2-pkce.1' \
    -o "$repo_root/dist/new-api-linux-amd64" .
)
sha256sum dist/new-api-linux-amd64 > dist/SHA256SUMS
printf '%s\n' 'Built Linux amd64 binary. No deployment or model request performed.'
