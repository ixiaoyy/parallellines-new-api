# ParallelLines Api

Pinned New API source plus the minimal opt-in PKCE login patch used by the
ParallelLines identity provider. The upstream UI is retained. Source is
**v0.13.2**, commit `bee339d279ccecbf8c8a89e14ddbbd902f78bd5d`; see
`upstream.lock.json` and [NOTICE.md](NOTICE.md). License: [AGPL v3](LICENSE).

## Prepare and build

On a Linux build machine with Bash, curl, unzip, Git, sha256sum, Go 1.26.1 and
Bun 1.4.4:

```sh
bash scripts/prepare-source.sh
bash scripts/build-local.sh
bash scripts/package-source.sh
docker build -f Dockerfile.runtime -t parallellines-newapi:v0.13.2-pkce.1 .
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
  -t parallellines-newapi:v0.13.2-pkce.1 \
  .build/new-api-bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
```

The Dockerfile retains official upstream builder digests and asserts Bun 1.4.4.
This container build path has not yet been executed by this packaging task. A
version mismatch must be resolved by reviewing an official builder digest; do
not bypass the assertion or substitute an unverified image. Source/versions are
pinned; bit-for-bit binary reproducibility across build machines is not claimed.

## Focused validation

From the prepared source directory, run the patch's affected tests:

```sh
go test ./pkg/oauthpkce
go test ./controller ./router -run '^TestCustomPKCE' -count=1
bun test ./web/src/helpers/api.pkce.test.js
```

The original build agent passed store, TLS-mock controller, route-registration,
and 11 frontend tests, built the frozen-lock frontend and Linux binary. Deployment
subsequently ran that binary. This repository preparation does not repeat model
calls or claim real per-user billing validation.

## What the patch does

`CUSTOM_OAUTH_PKCE_PROVIDERS=pingxingxian` enables S256 only for this named custom
provider. The server retains the verifier in a bounded short-lived transaction,
bound to browser session, principal, provider and provider configuration. State
is consumed atomically before token exchange. Keep a **single application
instance**: restart invalidates pending logins; shared multi-replica transaction
storage is not implemented.

The original OAuth + UserInfo subject binding remains. This patch does not
implement ID-token authentication, automatic administrator elevation, relay
tokens, or Chat-to-user quota attribution. Other providers retain their original
behavior when not explicitly opted in.

See [operations](docs/OPERATIONS.md) for native provider setup, authorization,
runtime secrets, deployment, source publication, and rollback.
