# Chat OAuth relay (v0.13.2-pkce.2)

This backend-only adapter preserves New API's original UI, OAuth login and relay
billing handlers. It grants no account, administrator role, wallet quota or
subscription. Native OAuth registration is a separate existing login flow; this
adapter only accepts an already bound and enabled native account.

## Fixed trust contract

Enable with `CHAT_OAUTH_RELAY_ENABLED=true`; every other value disables the adapter.
Retain `CUSTOM_OAUTH_PKCE_PROVIDERS=pingxingxian` for the existing S256 login patch.
No new secret, issuer URL or caller-selected identity configuration is introduced.

Every request sends its bearer access token only to
`https://pingxingxian.space/auth/oidc/me`, over normal verified HTTPS. There is no
positive identity cache, redirect following, ID-token authentication or nonce
claim. Verification has a five-second timeout and 16 KiB response limit. Required
UserInfo fields are:

| Claim | Required value |
| --- | --- |
| `iss` | `https://pingxingxian.space/auth/oidc` |
| `aud` | Single string `parallellines-openwebui` |
| `sub` | Exact, nonempty stable main-site subject |
| `pl_binding` | Nonempty current main-site session binding |
| `pl_auth_exp` | Integer epoch seconds strictly in the future |

The issuer must derive `aud` from the issued access token's actual client, and
revalidate the main-site session. New API or legacy client tokens cannot stand in
for Chat tokens. Native provider ID 1 must be enabled, have slug `pingxingxian`,
User ID field `sub`, and the exact fixed UserInfo URL. The database's unique
`user_oauth_bindings(provider_id, provider_user_id)` match supplies `user_id`.
Missing, ambiguous, changed, disabled or deleted bindings/accounts fail closed.
Email, request headers, cookies and request body user IDs never select an account.

## Narrow relay surface

Open WebUI uses base URL `https://api.pingxingxian.space/oauth-relay/v1` with
verified HTTPS, `auth_type=system_oauth`, an empty static API-key entry,
and `forward_cookies=false`. The only adapter endpoints are:

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/oauth-relay/v1/models` | Free discovery, even at zero wallet quota |
| POST | `/oauth-relay/v1/chat/completions` | Native Chat relay and billing |
| POST | `/oauth-relay/v1/responses` | Native Responses relay and billing |

The allowlist is exactly `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol`. Models are
listed in that order only when available in the user's native group. Listing does
not require model pricing or positive quota; paid requests retain native pricing,
quota, subscription, channel, rate-limit and settlement checks. Requests must be
JSON with an exact allowed model ID. Query strings, encoded adapter paths and
alternate credential/identity headers are rejected. Original canonical paths are
restored before native relay handlers. The OAuth bearer is replaced server-side;
it is never forwarded to a model channel. Streaming and image content use the
existing Chat/Responses body and native handlers, without an extra conversion.

No shared key fallback exists. A recovery administrator without a verified Chat
OAuth session cannot list through this adapter. No other API, image generation,
file, audio or embedding route is exposed by it.

## Credential storage and migration

The original GORM `AutoMigrate(&Token{})` adds nullable
`tokens.internal_purpose` (`varchar(64)`) and unique index
`ux_tokens_user_internal_purpose(user_id, internal_purpose)`. Normal tokens retain
NULL and may remain multiple per user. The internal purpose is `chat-oauth-v1`.
SQLite migration, idempotence, concurrent single-winner issuance and ordinary
token compatibility are tested. MySQL/PostgreSQL use the same portable GORM
schema but were not executed in this local verification.

The first verified request for an existing account creates one random server-only
credential in the New API database. Its model limit is the fixed three-model list;
group follows the user, cross-group retry is disabled, and no IP bypass is added.
`UnlimitedQuota=true` removes the redundant token budget only: native user wallet
or subscription enforcement remains mandatory. Initial token remaining quota is
zero; no user quota changes. The key is not emitted in responses, source or files.

Internal credentials are excluded from native token list/search/detail/key/update/
delete/batch APIs, including a root user's own token management. They also cannot
be used directly on ordinary relay or usage routes: TokenAuth requires the current
verified adapter context to match both token and user. Database backups are still
credentials and must remain private. Do not enable SQL parameter logging.

## Revocation and rollback

An authenticated root session, with the native matching `New-Api-User` header, can
call `POST /api/user/:id/oauth-relay/revoke`. It returns no key. An already issued
credential is disabled durably and its cache entry is invalidated. Repeated
revocation is idempotent. An absent credential returns 404 and does not create a
future-ban marker; disable the account or remove its native binding if issuance
must be prohibited before the first request. Disabled, expired, corrupt or
soft-deleted credentials are never automatically replaced or re-enabled. There
is no rotation/reset API in this release.

**Do not roll back to pkce.1 or stock v0.13.2 after any internal credential has
been issued.** Those binaries do not know the purpose guards and may expose the
stored key even if it is disabled. Before any old-binary rollback, stop/drain the
new service so no request can issue a credential, then run the read-only guard:

```sh
python3 scripts/guard-legacy-rollback.py /data/new-api.db
```

Any non-NULL internal-purpose row, including disabled or soft-deleted rows, blocks
that rollback. The guard queries only schema/counts and cannot repair or delete.
Safely stop the feature by keeping this binary and setting
`CHAT_OAUTH_RELAY_ENABLED=false`, or roll forward to a reviewed fix. Never restore
an old database automatically: it would discard later account and audit writes.

## Validation and limits

Tests cover two synthetic users with separate credential ownership, no quota or
role grants, concurrent issuance, counterfeit audience/issuer/session claims,
missing/ambiguous/inactive bindings, direct-key denial, hidden token APIs,
revocation and no recreation. Native BillingSession mocks settle two A requests
only against A; B stays unchanged. Actual router tests exercise Distribute and
Relay, returning `403 insufficient_user_quota` for zero-balance Chat/Responses
while allowing free model listing. All identity/model traffic is mocked; no paid
model calls were made. Successful live upstream billing, Redis-backed revocation,
production OAuth handoff and a container running this new binary remain deployment
checks, not claims of this local build.

The pinned upstream default price tables contain no entries for these three
models. An operator must configure verified upstream pricing in native options
before any authorized paid test. This patch does not guess prices, change the
New API quota-unit multiplier or grant initial balance. Missing native pricing is
allowed to reject a paid request.
