# Recorded source baseline

The deployed PKCE binary was built from New API v0.13.2 commit
`bee339d279ccecbf8c8a89e14ddbbd902f78bd5d` plus the exact patch in this repository.
The patch SHA-256 and upstream archive SHA-256 are pinned in `upstream.lock.json`.
Repository intake independently reapplied a clean-patch check to that verified
archive. Official UI assets were built using the frozen upstream Bun lockfile.

Historical deployed binary SHA-256:
`c8405c67977d845e557a8d56a9fd4c1b5694971b4b2ba6804f8d6ed01ad26e6d`.
Local image tag: `parallellines-newapi:v0.13.2-pkce.1`.
These identify the existing deployment; rebuilding elsewhere may produce a
different binary hash. Publish a fresh build's own checksum and source archive.

The original build/deployment verification covered focused PKCE store, mocked
controller and route tests, 11 frontend tests, frontend production build, Linux
binary build and runtime startup. This packaging task validated the Compose
schema without resolving runtime secret files. It did not rebuild Docker images,
execute paid model requests, or validate per-user quota attribution.

Public runtime files are normalized templates, not copies of live configuration.
No channel credentials, account IDs, authentication cookies, or audit logs are
part of this baseline.
