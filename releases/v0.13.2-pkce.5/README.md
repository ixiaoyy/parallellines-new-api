# v0.13.2-pkce.5

This release adds only the approved deleted-account session fix to pkce.4.
Three cookie authentication entry points check that the account still exists
and is not soft-deleted. Missing accounts are rejected. Database failures fail
closed with a generic error. Existing cookie role, status, name and group claims
keep their previous behavior. `FillUserById` now returns missing-account and
sanitized database errors. No account is deleted by this release or its deployer.

The exact increment is
`patches/new-api-v0.13.2-deleted-session-from-pkce4.patch`, SHA256
`13c4171b19f077bf7b581f5bd3433eeb93a77923cf80aa32bb988a164b5cf39b`.
The earlier broader session proposal is excluded. The six changed files and
their exact base/result hashes are in `patches/deleted-session-manifest.json`.
There is no schema change, secret rotation or role/balance mutation.

## Build and source

The release lock contains all three ordered patches against the verified
official v0.13.2 archive. Use Go 1.26.1, Linux amd64, CGO disabled and
`GOEXPERIMENT=greenteagc`. The verified 127 pkce.3/pkce.4 frontend assets are
unchanged and reused.

```sh
python3 releases/v0.13.2-pkce.5/prepare-source.py \
  --archive .build/upstream.zip --destination .build/pkce5-rebuild \
  --frontend /path/to/verified-pkce4/web/dist
SOURCE_DIR="$PWD/.build/pkce5-rebuild/new-api-bee339d279ccecbf8c8a89e14ddbbd902f78bd5d" \
  bash releases/v0.13.2-pkce.5/build.sh
```

Source packaging reconstructs public inputs and compares every source file to
the frozen binary build tree. It includes source, tests, licenses and recipes,
and excludes runtime data, credentials and compiled artifacts. Rebuild paths
can affect Go binary hashes; artifact checksums identify the deployed build.

## Small transport artifact

The 64-byte matcher emits exact copy operations and XOR differences against
bounded base byte ranges, compressed with gzip. The local generator and the
Python decoder both reconstructed the complete binary and verified its SHA256.
`apply-delta.py` also pins the archive and base binary hashes and both sizes,
limits decoded data and operations, validates all ranges, verifies the final
hash before writing, and refuses an existing output path. It has no service or
network operations.

```sh
python3 releases/v0.13.2-pkce.5/apply-delta.py \
  EXACT_PKCE4_BINARY PKCE5_DELTA_GZIP NEW_PKCE5_BINARY
```

Use only the artifact in `delta-evidence.json`, together with the pinned decoder.
The full gzip remains available. For an identical full gzip after reconstruction,
use Python `gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0,
compresslevel=9)` and check `artifact-checksums.json`.

## Deployment and boundaries

`deploy/deploy-deleted-session.py` accepts only pkce.4 to pkce.5. Normal activation
changes only the New API image. Existing billing, relay and Main profile flags
must remain true; provider scopes and credentials are not modified. The helper
checks archive/binary hashes, the database mount and service identity, takes a
consistent backup after stopping only New API, and verifies version and flags.
On activation failure it retains pkce.5 and disables relay; it never restores a
database or old binary. Existing receipt/image requires inspection before retry.

The release builder ran the affected model/middleware tests and transport
boundary tests offline. Startup smoke does not prove user deletion or actual
replay against production. The parent operator handles any specifically
authorized account cleanup and live verification. No paid model call is made.
