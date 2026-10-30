# Operations

## Runtime and secrets

Use `compose.yaml` as a reference for the existing deployment. Fill `.env.example`
outside the checkout with the current project, image, data mount, network and
secret-file paths. Do not start new defaults against an existing service. The
image tag must identify a reviewed build; record its immutable digest before use.
Keep new data under `/data`. Existing session/crypto secrets must survive upgrades.
Filled files are server-only, in mode 0700 directories and mode 0600 files.

Compose publishes only `127.0.0.1:13000`; public access goes through the explicitly
attached Nginx edge network. Do not expose raw ports. Validate with
`docker compose --env-file /data/parallellines/api/deploy.env config --quiet`.
Do not emit expanded Compose configuration into shared logs.

## Native login provider

Use New API's existing root session in its native UI/API; no extra management
token is required. Register a custom OAuth provider with slug `pingxingxian`:

| Field | Value |
| --- | --- |
| client ID | `parallellines-newapi` |
| client secret | Independent server-only value registered with the identity bridge |
| discovery | `https://pingxingxian.space/auth/oidc/.well-known/openid-configuration` |
| authorization/token/UserInfo URLs | Exact values from verified issuer discovery |
| scopes | `openid profile` |
| User ID field | `sub` |
| username / display name | `preferred_username` / `name` |
| email field | `email` (optional; do not use for identity merging) |
| auth_style | `2` (`client_secret_basic`) |
| callback | `https://api.pingxingxian.space/oauth/pingxingxian` |

The current fixed-version native API is `POST /api/custom-oauth-provider/`.
Authenticate normally and send the matching `New-Api-User` header. Do not record
request bodies, secret values, cookies, or authorization headers. Provider GET
responses and the create response omit the client secret entirely.

Set native options individually, retaining unrelated settings:

```json
{"key":"ServerAddress","value":"https://api.pingxingxian.space"}
{"key":"PasswordRegisterEnabled","value":"false"}
{"key":"RegisterEnabled","value":"true"}
```

`RegisterEnabled` permits first-time OAuth account creation; password registration
remains disabled. Preserve existing root password login as recovery until a
verified owner handover. New accounts have the ordinary role (1), with no default
or invitation quota grants. A normal account may have a personal console but
must not manage channels, other users, or quotas. Bind an administrator only
through an authenticated existing-admin flow after checking the stable main-site
subject and role; no email inference or role inheritance is implemented.

## Models and quotas

Do not store real channel keys in repository files. Keep them server-side and
configure through the native administrator contract. For the OpenAI-compatible
type 1 channel, the base URL is an origin without `/v1`; relay appends the API
path. Confirm actual upstream model IDs before configuration.

The requested catalog is `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol`, with Luna
preferred. This document does not create channels, allocate credits, or validate
paid requests. Set native `monitor_setting.auto_test_channel_enabled=false`,
`CHANNEL_TEST_FREQUENCY=0`, and the channel's settings JSON flags
`upstream_model_update_check_enabled=false` and
`upstream_model_update_auto_sync_enabled=false` when paid automated checks are not
approved. The channel `settings` field itself is a JSON string.

Quota accounting is New API-specific. Do not copy LibreChat credit conversions.
SSO establishes identity. Version pkce.2 adds a separate opt-in adapter that maps
verified Chat-client UserInfo to an exact existing native OAuth binding and uses
an independent internal credential per user. See [OAUTH-RELAY.md](OAUTH-RELAY.md)
for its fixed claims, migration, routes, zero-quota model discovery and limits.
Do not pass an SSO access token to stock relay routes or give users a shared key.

## Upgrade and rollback

1. Release source and reviewed patch from Git. Check source and patch hashes;
   run focused tests. Build off-server or on the data disk. The existing binary
   artifact can be installed through `Dockerfile.runtime` only after verifying
   its release checksum; never copy an unknown binary over a mutable image tag.
2. Back up the target SQLite database consistently and preserve the matching
   image digest, service definition and source release. Keep backups private.
3. Recreate only this service, retaining existing data and secret mounts. Check
   startup, `/api/status`, enabled login provider, and ordinary/admin permission
   boundaries. This does not require a model completion request.
4. Publish and link the exact full corresponding source archive for the deployed
   AGPL version. Preserve old source releases while deployed versions remain.

After any internal Chat credential is issued, stock v0.13.2 and pkce.1 are unsafe
rollback targets: they lack the internal-key visibility and direct-use guards.
Keep pkce.2 and disable `CHAT_OAUTH_RELAY_ENABLED`, or roll forward. For a proposed
old-binary rollback, first stop/drain issuance and run
`python3 scripts/guard-legacy-rollback.py /data/new-api.db` against the actual DB;
any non-NULL internal-purpose row (even disabled/soft-deleted) blocks rollback.
This read-only guard never deletes credentials or restores data. Never blindly
restore a pre-upgrade database because post-backup writes would be lost. Preserve
root recovery and all volumes; do not prune images or affect other services.

## Nginx

`deploy/nginx-api.conf` is an additive vhost, not a replacement for the main
configuration. Ensure its certificate exists, attach Nginx to the specified edge
network without losing its other networks/gateway, and make the upstream alias
resolve correctly. Validate `nginx -t`, reload safely, and verify existing hosts
as well as the API host. Preserve inode when changing a single-file bind mount.
Verify certificate-renewal reload hooks separately; a renewal timer alone is not
evidence that Nginx has loaded renewed certificates.
