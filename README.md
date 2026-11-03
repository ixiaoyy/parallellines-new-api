# ParallelLines Api

Pinned New API source plus opt-in PKCE login, trusted Chat OAuth relay, and standard billing patches
used by the ParallelLines identity provider. The upstream UI is retained. Source is
**v0.13.2**, commit `bee339d279ccecbf8c8a89e14ddbbd902f78bd5d`; see
`upstream.lock.json` and [NOTICE.md](NOTICE.md). License: [AGPL v3](LICENSE).

## Current release

The latest prepared release recipe is **v0.13.2-pkce.9**. Start with its
[release instructions](releases/v0.13.2-pkce.9/README.md)
and [ordered release lock](releases/v0.13.2-pkce.9/upstream.lock.json).
It retains the [pkce.8 guarded free Chat baseline](releases/v0.13.2-pkce.8/README.md),
adding frontend route/language loading, bounded collision existence checks,
request-stage access timings and complete public frontend embedding. Ordinary
no-conflict account checks have no demonstrated speedup. Existing balances,
credential restrictions, role synchronization, paid/free billing and timeouts
are retained. The image-only release path preserves every current environment
setting, including the already configured free-model gate; it does not reactivate
features or change identity TTLs. Local compilation and isolated checks do not
prove production activation or real model behavior. The last public preflight
still reported pkce.8; actual activation belongs to the private deployment receipt.
The root lock and
the base-build commands below intentionally describe the reusable pkce.3 base;
do not use that base image to replace the current live release.

The source archives and manifests describe application source only. Runtime
secrets, databases, identities and logs are excluded from version control.

## Prepare and build

On a Linux build machine with Bash, curl, unzip, Git, sha256sum, Go 1.26.1 and
Bun 1.4.4:

```sh
bash scripts/prepare-source.sh
bash scripts/build-local.sh
bash scripts/package-source.sh
docker build -f Dockerfile.runtime -t parallellines-newapi:v0.13.2-pkce.3 .
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
  -t parallellines-newapi:v0.13.2-pkce.3 \
  .build/new-api-bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
```

The Dockerfile retains official upstream builder digests and asserts Bun 1.4.4.
This container build path has not yet been executed by this packaging task. A
version mismatch must be resolved by reviewing an official builder digest; do
not bypass the assertion or substitute an unverified image. Source/versions are
pinned; bit-for-bit binary reproducibility across build machines is not claimed.
The pkce.3 release rebuilds the native pricing details and server; do not reuse
pkce.1 or pkce.2 frontend assets. This upstream frontend displays the version
returned by server status rather than embedding the Vite version variable.
Verify the released index and asset hashes when checking for stale frontend files.

## Focused validation

From the prepared source directory, run the patch's affected tests:

```sh
go test ./pkg/oauthpkce
go test ./model ./middleware ./controller ./router -count=1
bun test ./web/src/helpers/api.pkce.test.js
bun test ./web/src/helpers/openai-standard-pricing.test.js
```

The initial PKCE release passed store, TLS-mock controller, route-registration,
and 11 frontend tests, built the frozen-lock frontend and Linux binary, and was
deployed as pkce.1. The pkce.2 relay build passed the affected Go packages and
deployment guard tests. Its activation is a separate deployment step. This
repository preparation does not make model calls or claim real per-user billing
validation.

The pkce.3 billing policy and native display share reviewed standard-rate metadata.
It applies only to the exact three models on direct official OpenAI Chat
Completions/Responses. Actual cache-write usage and long-context conditions are
handled explicitly; missing or invalid usage is an error, not an estimated or
successful zero-cost response. See the patched source's
`docs/OPENAI-STANDARD-BILLING.md` and `docs/OPENAI-STANDARD-PRICING-DISPLAY.md`, plus
[the deployment procedure](docs/STANDARD-BILLING-RELEASE.md). No balances are
assigned and no claim of exact upstream invoice parity is made.

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
They verify the fixed issuer's current Chat-client UserInfo and exact native
binding, then use an independent server-only restricted credential through
native user billing. By default no account is created by the adapter. The pkce.7
account-sync flag additionally provisions a missing native binding from verified
Main profile/role claims, retaining native registration policy. No existing balance
is changed. Free model
listing works at zero quota. See [the trust contract, migration and revocation
rules](docs/OAUTH-RELAY.md).

Once an internal credential exists, old binaries are unsafe rollback targets.
Use `scripts/guard-legacy-rollback.py` before any such rollback; keep this version
with its adapter disabled if the guard refuses. See operations for details.

See [operations](docs/OPERATIONS.md) for native provider setup, authorization,
runtime secrets, deployment, source publication, and rollback.
