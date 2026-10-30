# ParallelLines Api

Pinned New API source plus opt-in PKCE login and trusted Chat OAuth relay patches
used by the ParallelLines identity provider. The upstream UI is retained. Source is
**v0.13.2**, commit `bee339d279ccecbf8c8a89e14ddbbd902f78bd5d`; see
`upstream.lock.json` and [NOTICE.md](NOTICE.md). License: [AGPL v3](LICENSE).

## Prepare and build

On a Linux build machine with Bash, curl, unzip, Git, sha256sum, Go 1.26.1 and
Bun 1.4.4:

```sh
bash scripts/prepare-source.sh
bash scripts/build-local.sh
bash scripts/package-source.sh
docker build -f Dockerfile.runtime -t parallellines-newapi:v0.13.2-pkce.2 .
```

The preparation checks the upstream archive and patch SHA-256 before applying the
patch. Build uses the upstream frozen Bun lockfile and Go module checksums. It
produces Linux amd64 with CGO disabled and `GOEXPERIMENT=greenteagc`. Build outputs
and full downloaded upstream source are ignored by Git. Publish the generated
corresponding-source archive with each deployed release.

For a downloaded corresponding-source release (which already contains patched
`source/`), skip preparation and build with
`SOURCE_DIR=source bash scripts/build-local.sh`. The Docker alternative below uses
`source` as the context in that release. Keep source and release metadata together.

A pinned-container alternative uses the prepared source as its build context:

```sh
docker build -f "$PWD/Dockerfile" \
  -t parallellines-newapi:v0.13.2-pkce.2 \
  .build/new-api-bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
```

The Dockerfile retains official upstream builder digests and asserts Bun 1.4.4.
This container build path has not yet been executed by this packaging task. A
version mismatch must be resolved by reviewing an official builder digest; do
not bypass the assertion or substitute an unverified image. Source/versions are
pinned; bit-for-bit binary reproducibility across build machines is not claimed.
This backend-only pkce.2 release reuses the validated frontend assets; its frontend
build stamp remains pkce.1 while the server version is pkce.2. The build recipes
retain that same stamp.

## Focused validation

From the prepared source directory, run the patch's affected tests:

```sh
go test ./pkg/oauthpkce
go test ./model ./middleware ./controller ./router -count=1
bun test ./web/src/helpers/api.pkce.test.js
```

The initial PKCE release passed store, TLS-mock controller, route-registration,
and 11 frontend tests, built the frozen-lock frontend and Linux binary, and was
deployed as pkce.1. The pkce.2 relay build passed the affected Go packages and
deployment guard tests. Its activation is a separate deployment step. This
repository preparation does not make model calls or claim real per-user billing
validation.

## What the patch does

`CUSTOM_OAUTH_PKCE_PROVIDERS=pingxingxian` enables S256 only for this named custom
provider. The server retains the verifier in a bounded short-lived transaction,
bound to browser session, principal, provider and provider configuration. State
is consumed atomically before token exchange. Keep a **single application
instance**: restart invalidates pending logins; shared multi-replica transaction
storage is not implemented.

The original OAuth + UserInfo subject binding remains. Other login providers
retain their original behavior when not explicitly opted in. No ID-token
authentication or automatic administrator elevation is introduced.

`CHAT_OAUTH_RELAY_ENABLED=true` enables the three dedicated Chat relay routes.
They verify the fixed issuer's current Chat-client UserInfo and exact existing
native binding, then use an independent server-only restricted credential through
native user billing. No account or balance is created by the adapter. Free model
listing works at zero quota. See [the trust contract, migration and revocation
rules](docs/OAUTH-RELAY.md).

Once an internal credential exists, old binaries are unsafe rollback targets.
Use `scripts/guard-legacy-rollback.py` before any such rollback; keep this version
with its adapter disabled if the guard refuses. See operations for details.

See [operations](docs/OPERATIONS.md) for native provider setup, authorization,
runtime secrets, deployment, source publication, and rollback.
