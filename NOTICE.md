# Source and modifications

This project packages New API v0.13.2, upstream commit
`bee339d279ccecbf8c8a89e14ddbbd902f78bd5d`, by QuantumNous and its contributors.
The upstream application and this modification are provided under GNU AGPL v3;
the complete license is in [LICENSE](LICENSE). Original UI and notices are retained.

Modification dated 2026-10-30: an opt-in, provider-specific OAuth PKCE flow with
short-lived, single-use, server-side transactions and associated tests; plus an
opt-in, fixed-issuer Chat OAuth adapter using existing native user bindings and
independent server-only credentials through the original billing pipeline. The
patch grants no administrator roles, accounts, quota or subscription.

The pkce.3 modification adds an opt-in standard OpenAI billing policy for three
explicit models, including checked upstream usage, cache-write and long-context
accounting, and policy details in the original pricing interface. The quota
schedule is a site policy, not a guarantee of the operator's actual invoice.

The fixed upstream archive plus the combined patch named in `upstream.lock.json` describe the
modified source. `scripts/package-source.sh` assembles the full corresponding
source, dependency lockfiles, build scripts, patch, and license into a release
archive. Publish that archive alongside every deployed modified version and make
its exact URL available to users interacting with the service. Keep older release
source available while those versions are deployed. A binary alone is insufficient.

This repository is an independent deployment project; upstream names do not imply
endorsement. Dependency components retain their respective licenses.
