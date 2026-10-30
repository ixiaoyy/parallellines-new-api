# Standard billing release procedure

The pkce.3 release is a backend-only billing compatibility update for the three
explicitly selected OpenAI models. It preserves the pinned upstream UI and the
pkce.2 identity/token guards. The site's quota policy uses the reviewed OpenAI
public standard schedule, not a guarantee of the operator's eventual invoice.

## Freeze and build

Do not run source preparation over a working implementation tree. After the
application patch and focused tests are frozen:

1. Export the cumulative patch against the pinned upstream commit, preserving
   PKCE, personal credential hiding, and billing changes. Verify application to a
   fresh copy of the SHA-checked upstream archive and reverse-check it.
2. Update `upstream.lock.json`, build/version stamps and patch checksums together.
   Keep the unchanged frontend assets/build stamp at pkce.1. Build Linux amd64
   with Go 1.26.1, CGO off and the existing `greenteagc` setting.
3. Produce the gzip binary, hashes, focused test evidence, and corresponding-source
   archive from verified frozen inputs. No runtime configuration, database, log,
   private account data or credential belongs in the source package.
4. Verify the remote archive SHA before invoking a deployment helper. An interrupted
   transfer or deployment must be inspected before retrying.

## Activate

Keep `deploy/deploy-standard-billing.py` and `deploy/deploy-personal-relay.py`
together on the server. The new helper reuses only the latter's reviewed utility
functions. Supply the same nonsecret scope shape, with these exact release values:

```json
{
  "expected_image": "parallellines-newapi:v0.13.2-pkce.2",
  "image": "parallellines-newapi:v0.13.2-pkce.3",
  "version": "v0.13.2-pkce.3"
}
```

The complete scope also requires `work_dir`, `archive`, `archive_sha256`,
`binary_sha256`, `container`, `compose`, `database`, `receipt`, and `status_url`.
Artifacts, backups and receipts stay under `/data`. The status URL must use
loopback. Use a new receipt path for this release; never erase a prior receipt to
force a rerun.

```sh
python3 deploy-standard-billing.py /data/approved-release/scope.json
```

Only the New API image and `OPENAI_STANDARD_BILLING_ENABLED=true` are enabled;
existing OAuth relay and PKCE flags remain in place. Other Compose service bytes,
secret-file paths, roles, balances and native price options are preserved. The
helper checks the mounted database path, builds the frozen official runtime
overlay, runs a network-isolated smoke container, then stops only New API for a
consistent private database backup and service recreation. It makes no model
request and never restores the database.

## Failure and verification

Recovery is deliberately forward-only. Keep pkce.3 and the billing policy enabled,
disable the Chat OAuth relay, and verify health. If that cannot start, leave only
New API stopped for operator recovery. Neither pkce.1 nor pkce.2 is automatically
restored, and no database/ledger rollback is performed. This avoids running old
accounting against activity that may have occurred during activation.

The helper reports a successful version/health/flag check, not actual upstream
settlement. After deployment, inspect only the relevant effective flags, exact
model policy scope, retained identity mappings and unchanged balances. Use free
model-directory or mocked usage tests. Paid requests require separate approval.
