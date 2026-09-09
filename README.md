🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Keysso MCP

MCP server for Keys.so SEO reports. An AI assistant can retrieve keyword, competitor, advertising and backlink data through the supported report API.

## What you can do

- Browse the report catalogue at `keysso://reports`.
- Request a report with `keys_so_query`, using its documented path and parameters.
- Read report data within a fixed list of supported endpoints and parameters.

## Quick start

Install Python 3.12+ (below 3.15), [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git.

You need a Keys.so API token and access to the reports you want to use. The wizard saves the token in a private local file.

```sh
git clone https://github.com/zai-one/keysso-mcp.git
cd keysso-mcp
uv sync --frozen
uv run --frozen python scripts/configure.py
uv run --frozen keysso-mcp --config mcp.local.json --check-config
uv run --frozen keysso-mcp --config mcp.local.json
```

The last command starts stdio and waits for an MCP client; it is not an interactive chat.
See [INSTALL.md](INSTALL.md) for credentials, client configuration, HTTP and package integration.
`--check-config` checks local settings only; it never validates a provider account over the network.

## Scope and limits

This server exposes read-only reports. Available data and request limits depend on your Keys.so account. See [request limits and access settings](docs/RUNTIME.md).

## Verification

```sh
uv sync --frozen --all-groups
uv run --frozen python scripts/verify.py
uv run --frozen python scripts/verify_install.py
```

Tests use synthetic fixtures. A passing test run does not establish live provider connectivity.

## Use and feedback

You may install and use this project for your own accounts under [LicenseRef-ZAI-ONE](LICENSE).
This is not an open-source license. Third-party notices remain in [NOTICE](NOTICE).
If it helps, give the repository a ⭐. Missing something or found a bug? [Open an issue](https://github.com/zai-one/keysso-mcp/issues/new/choose).
I'm working on this project; accepted improvements are implemented here. Support is not guaranteed.
