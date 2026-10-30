# Source and modifications

This project packages New API v0.13.2, upstream commit
`bee339d279ccecbf8c8a89e14ddbbd902f78bd5d`, by QuantumNous and its contributors.
The upstream application and this modification are provided under GNU AGPL v3;
the complete license is in [LICENSE](LICENSE). Original UI and notices are retained.

Modification dated 2026-10-30: an opt-in, provider-specific OAuth PKCE flow with
short-lived, single-use, server-side transactions and associated tests. The patch
does not grant administrator roles or implement per-user model billing.

The fixed upstream archive plus `patches/new-api-v0.13.2-pkce.patch` describe the
modified source. `scripts/package-source.sh` assembles the full corresponding
source, dependency lockfiles, build scripts, patch, and license into a release
archive. Publish that archive alongside every deployed modified version and make
its exact URL available to users interacting with the service. Keep older release
source available while those versions are deployed. A binary alone is insufficient.

This repository is an independent deployment project; upstream names do not imply
endorsement. Dependency components retain their respective licenses.
