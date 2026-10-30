# Main profile increment after pkce.3

This independent increment preserves the pkce.3 billing/pricing release inputs.
It is not applied by the existing `prepare-source.sh` automatically.

After preparing a fresh pkce.3 source directory, run:

```sh
python scripts/apply-profile-sync.py .build/new-api-bee339d279ccecbf8c8a89e14ddbbd902f78bd5d
```

The helper checks the patch digest, both changed source baselines, four absent
new files, and all six resulting hashes. A second application refuses safely.
Build this resulting source under a distinct profile release image/version; do
not overwrite a frozen pkce.3 binary or reuse its receipt. Frontend assets remain
the same as pkce.3. Follow the existing controlled deployment procedure and keep
its old image, secrets, data, health probes and rollback reference.

Only after Main and its identity bridge support current verified profile claims:

- Set `MAIN_OAUTH_PROFILE_SYNC_ENABLED=true` on this increment's NewAPI service.
- Keep the existing enabled provider ID `1`, slug `pingxingxian`, client ID
  `parallellines-newapi`, Basic client authentication, and S256 PKCE.
- Keep fixed endpoints under `https://pingxingxian.space/auth/oidc`:
  `/auth`, `/token`, `/me`. Request scopes `openid profile email`.
- Preserve field mappings `sub`, `preferred_username`, `name`, and `email`.
  Do not create another provider or modify any stable user binding.

Each successful Main login finds the existing user only by provider ID + subject,
then updates `username`, `display_name`, and `email` in one transaction. Email
must carry a JSON boolean `email_verified: true` from the exact issuer/client.
Conflicts (including soft-deleted users) reject login without merging or generating
a substitute username. Other providers follow their existing paths. Roles,
passwords, balances, token ownership and stable IDs are not synchronized.

Original validation limits remain: username at most 20 Unicode characters, display name
20 characters, email 50 characters. Oversized Main profiles fail clearly; nothing
is truncated. A concurrent or failed database write fails the login safely with
generic error text, without profile SQL values in logs. Existing user sessions
must sign out and sign in using Main to refresh their local profile.

Tests use only synthetic identities and SQLite/loopback fixtures. No production
user, real email, upstream key or billable model request is used.
