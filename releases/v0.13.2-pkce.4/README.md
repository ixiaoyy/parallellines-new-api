# v0.13.2-pkce.4

This release adds the approved Main identity profile synchronization to the
frozen pkce.3 billing release. It contains exactly the two ordered patches in
`upstream.lock.json`. The optional session revocation patch is **not included**.
The root pkce.3 lock and its release artifacts remain unchanged.

## Build and source

Use Go 1.26.1, CGO disabled, Linux amd64 and `GOEXPERIMENT=greenteagc`.
`prepare-source.py` verifies the official archive and both patches, then applies
them in order into a new directory. It refuses an existing destination.

```sh
python3 releases/v0.13.2-pkce.4/prepare-source.py \
  --archive .build/upstream.zip --destination .build/pkce4-rebuild \
  --frontend /path/to/verified-pkce3/web/dist
SOURCE_DIR="$PWD/.build/pkce4-rebuild/new-api-bee339d279ccecbf8c8a89e14ddbbd902f78bd5d" \
  bash releases/v0.13.2-pkce.4/build.sh
```

The 423 frontend source inputs are unchanged from pkce.3. The deployed binary
reuses its 127 individually verified assets, including native pricing details.
Omit `--frontend` to build them with Bun 1.4.4 and the upstream frozen lockfile.
The release source archive includes all application source, licenses, ordered
patches and the release/build/deployment recipes. It excludes runtime data,
credentials, compiled frontend assets and binaries. Rebuilding with different
absolute source paths can change the Go binary hash; the deployed binary's
exact hash is in `artifact-checksums.json`.

## Deployment contract

The operator runs `deploy/deploy-profile-sync.py <nonsecret-scope.json>` beside
`deploy-personal-relay.py`, after verifying both file hashes. Use the existing
scope schema, exact pkce.3 image as `expected_image`, pkce.4 as `image` and
`version`, and this release's binary/archive hashes. All artifacts, backup,
database and receipt paths are on `/data`; compose can remain under `/opt`.
The operator must set `verified_main_email_claims: true` only after independently
verifying the deployed Main and bridge support verified email claims.

The helper requires the active New API database mount and provider ID 1 to
match the reviewed contract. It stops only New API, verifies it is stopped,
takes a consistent SQLite backup, and uses a transaction to change only
provider scopes from `openid profile` to `openid profile email`. Client secrets,
endpoints, identity bindings, role, profile and balance records are not changed
by the deployer. Profile updates occur through the authenticated application
flow after release.

The helper preserves `OPENAI_STANDARD_BILLING_ENABLED=true` and
`CHAT_OAUTH_RELAY_ENABLED=true`, and adds `MAIN_OAUTH_PROFILE_SYNC_ENABLED=true`.
If activation fails it keeps the new binary and both policy flags enabled,
disables relay and requires operator inspection. It never restores the database
or the old binary. If an image/receipt already exists, inspect the previous
attempt before retrying. There is no automatic retry or rollback across billing.

## Verification limits

Profile, PKCE and key billing tests plus deployment fixture tests passed.
Deployment smoke checks prove startup and expected flags only. No paid model
request, balance change or actual end-user profile update was performed by the
release builder. The operator and user verify live behavior after deployment.
