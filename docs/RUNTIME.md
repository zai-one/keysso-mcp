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

## Opt-in paid and writing tools

The default toolsets are read-only. The opt-in toolsets `jobs`, `monitoring` and `api`
(`KEYSSO_TOOLSETS=all` or by name; removed by `KEYSSO_READ_ONLY=1`) can spend plan limits or
change saved data. Each such call needs a single-use, request-bound approval that the operator
accepts outside MCP with `keysso-approval` (file `keysso-approvals.json` next to the state
database, 30-minute TTL). Over HTTP these tools are authorized by the same `keys_so:read`
scope, so enable them on an HTTP deployment only when every token holder may request paid work.

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

## Update check

`keysso_check_update` compares the installed version with the latest GitHub
release and suggests an install command; nothing is installed automatically.
Unless `KEYSSO_DISABLE_UPDATE_CHECK=1` is set, the server calls `api.github.com`
(anonymous, at most once a day) in a background thread at startup and when the
tool runs, so HTTP/server deployments make this outbound request too. The result
is cached in `update-check.json` next to the state database. Every attempt is
recorded there: after a failure the next request waits 30 minutes, and
`force_refresh` is honoured at most once a minute. Only plain version tags
(`v1.2.3`) are accepted. The tool goes through the same authorization and
audit as the other tools (in delegated mode, `tool: "keysso_check_update"` and
`request_hash` of `{"force_refresh": ...}`), but spends no Keys.so quota.

## Release checks

See [installation and verification](../INSTALL.md). No live provider requests run in offline tests.
