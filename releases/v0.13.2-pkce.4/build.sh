#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ "$(go env GOVERSION)" == 'go1.26.1' ]] || { echo 'Go 1.26.1 required' >&2; exit 1; }
source_dir=${SOURCE_DIR:?Set SOURCE_DIR to a fresh prepare-source.py output}
repo_root="$PWD"
# prepare-source.py --frontend verifies all reused pkce.3 assets. When no
# frontend was reused, build identical unchanged sources with the locked tools.
if [[ ! -f "$source_dir/web/dist/index.html" ]]; then
  [[ "$(bun --version)" == '1.4.4' ]] || { echo 'Bun 1.4.4 required' >&2; exit 1; }
  (cd "$source_dir/web" && bun install --frozen-lockfile &&
   DISABLE_ESLINT_PLUGIN=true VITE_REACT_APP_VERSION=v0.13.2-pkce.4 bun run build)
fi
mkdir -p dist/pkce4-rebuild
(
  cd "$source_dir"
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOEXPERIMENT=greenteagc \
    go build -buildvcs=false \
    -ldflags '-s -w -X github.com/QuantumNous/new-api/common.Version=v0.13.2-pkce.4' \
    -o "$repo_root/dist/pkce4-rebuild/new-api-linux-amd64" .
)
sha256sum dist/pkce4-rebuild/new-api-linux-amd64 > dist/pkce4-rebuild/SHA256SUMS
printf '%s\n' 'Built local release; no server or model request performed.'
