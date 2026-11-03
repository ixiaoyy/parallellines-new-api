# v0.13.2-pkce.9 — performance prerelease

Source-published prerelease, not a claim of production activation.

- Loads console pages and non-fallback languages on demand; retains routes, permissions and supported languages.
- Adds request-stage timing fields to the existing OAuth relay access log without redefining `frt` or logging identity payloads.
- Stops profile collision checks at the first match with the exact existing predicate and transaction/lock/error semantics. No demonstrated speedup for the ordinary no-conflict path; synthetic early-match benefits are not end-to-end latency claims.
- Includes all 197 reviewed public frontend files, including two underscore-prefixed dependencies, in the Go binary. Checks 965 parsed module/style/HTML references and the real embedded filesystem/static serving path.
- Preserves current paid/free billing, identity TTLs, feature gates, quotas, credentials, volumes and timeouts. No schema migration or index change; no drain/maintenance policy.

The deployment helper only updates the reviewed `newapi` image/build and can restore the captured pkce.8 service definition without restoring an old business database. Shared Nginx activation and server cleanup remain separately coordinated.

The exact expanded corresponding source, frozen frontend manifests and original build inputs are attached. The source receipt identifies the application-code commit, archive digest and binary digest. Local/isolated checks do not establish real OAuth/model behavior or production activation; no paid model request was made.
