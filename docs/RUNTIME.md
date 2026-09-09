# Keysso MCP

Standalone Keys.so MCP with the existing `keys_so_query(path, params)` tool.
It returns `{"payload": ...}` and restricts requests to a fixed read-only report
and parameter allowlist. Its source was extracted from the committed platform
baseline recorded in `SOURCE_PROVENANCE.json`.

## Install and run

Requires Python 3.12–3.14. Run `uv sync --frozen --all-groups` and set
`KEYSSO_API_TOKEN_FILE` to an owner-private text file containing your API token.
No AI Kit installation or central platform package is required.

`uv run keysso-mcp` starts stdio for the local operator. The OS process boundary
owns that identity; this mode must not be exposed as an unauthenticated network
bridge. State defaults to `state/keysso.sqlite`.

`uv run keysso-mcp --transport http` binds to `127.0.0.1:8811/mcp` and requires
`KEYSSO_MCP_PUBLIC_KEY_FILE`, an RSA public key. The client bearer JWT must use
RS256, match `KEYSSO_MCP_ISSUER` (default `keysso-operator`) and
`KEYSSO_MCP_AUDIENCE` (default `keysso-mcp`), and contain `sub`, `exp`,
`scope: "keys_so:read"`, and `account_id` matching `KEYSSO_ACCOUNT_ID` (default
`default`). Use a trusted issuer; private signing keys never belong in this repo.

## Central gateway mode

Set `KEYSSO_AUTH_MODE=delegated`. Every tool invocation needs a fresh signed JWT
with `iat`, `exp` (at most 60 seconds after `iat`), `jti`, `request_id`,
`tool: "keys_so_query"`, and `request_hash`: SHA-256 of the compact, sorted-key
JSON object `{"path": ..., "params": ...}` encoded as UTF-8 with
`ensure_ascii=False` (see `transport.canonical_json`).
The same token may complete MCP initialization and discovery, but can execute
only one matching tool call. Identity/account are signed claims, never tool
arguments. Delegated mode performs exactly one upstream attempt; the gateway
owns retry admission and issues a fresh bounded token for each admitted retry.

The SQLite ledger atomically rejects replay across restarts/processes and limits
every upstream attempt per account and principal. Configure `KEYSSO_RATE_LIMIT`
and `KEYSSO_PRINCIPAL_RATE_LIMIT` (both default 10/minute), and
`KEYSSO_MAX_CONCURRENCY` (default 1). Upstream cooldowns persist across restarts.
Use one shared local
ledger per account on a single host; multi-host replication requires a different
coordinated ledger and is not supported in this release.

Use private service-to-service networking plus TLS termination for deployment;
HTTP bearer authentication is mandatory even on the private network.

## Release checks

See [installation and verification](../INSTALL.md). No live provider requests run in offline tests.
