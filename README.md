🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Keys.so MCP

**Turn competitor data into your next SEO investigation.**

Ask which keywords a competing domain ranks for, inspect its ads or explore its backlink sources. Keys.so MCP brings supported Keys.so reports into your assistant, so you can ask follow-up questions against the same source data instead of preparing a new export for each question.

[Quick start](#quick-start) · [Connect your assistant](#connect-your-assistant) · [Issues](https://github.com/zai-one/keysso-mcp/issues)

Try asking your assistant:

> Get the organic keyword report for example.com. Group the returned queries by topic and suggest which groups deserve a closer look.

## What you can do

| Your task | What the MCP server provides |
|---|---|
| Explore a competitor | Domain summaries, organic keywords, competing domains and landing-page reports. |
| Review advertising | Available ad, paid-keyword and advertising-history reports. |
| Investigate links | Backlinks, referring domains, anchors and linked-page reports. |

## Quick start

Prefer a ready package? [Install the release and generate your client configuration](INSTALL.md#install-a-release-package). No source checkout is required.

Install **Python 3.12–3.14** and [uv](https://docs.astral.sh/uv/getting-started/installation/). Clone with Git or [download the ZIP](https://github.com/zai-one/keysso-mcp/archive/refs/heads/main.zip). With a ZIP, open the extracted directory and skip the first two commands.

You need a Keys.so API token and access to the reports you want to use. The wizard saves the token in a private local file.

```sh
git clone https://github.com/zai-one/keysso-mcp.git
cd keysso-mcp
uv sync --frozen
uv run --frozen python scripts/configure.py
uv run --frozen keysso-mcp --config mcp.local.json --check-config
```

The wizard creates a local configuration and stores secrets in private files. It refuses to overwrite an existing setup. `--check-config` validates local settings; the first request below checks your account connection.

## Connect your assistant

Add this configuration to an MCP client that uses `mcpServers`, such as Claude Desktop or Cursor. Replace `/ABSOLUTE/PATH/` with your absolute path; Windows JSON paths can use forward slashes, such as `D:/Tools/`.

```json
{
  "mcpServers": {
    "keysso": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/keysso-mcp",
        "run",
        "--frozen",
        "keysso-mcp",
        "--config",
        "/ABSOLUTE/PATH/keysso-mcp/mcp.local.json"
      ]
    }
  }
}
```

The client starts the MCP server for you. Refresh its tool list, then make your first request. For clients with a different config format, reuse the same `command` and `args`; `uv` must be available to the client process.

### First request

> Open keysso://reports and show me which reports are available. Then retrieve the domain overview for my site.

The catalogue lists supported reports and parameters without spending an API request. A domain query returns Keys.so data using your token. Supply your domain and the database/region you want to analyse.

If tools do not appear, check the absolute path, whether the client can find `uv`, and the `--check-config` result. For access errors, check account credentials and permissions. [Installation and troubleshooting](INSTALL.md).

## Access and limits

Use `keysso_domain_report` for keywords, competitors, pages or backlinks, and `keysso_compare_domains` for overlaps and gaps. Each can collect up to five pages and return JSON or CSV with source and completeness fields. The original `keys_so_query` still requests one page. [Report examples and limits](docs/REPORTS.md).

Ask: “Export a competitor’s keywords excluding my domain, in CSV. Show whether the sample is complete.”

This server exposes read-only reports. Available data and request limits depend on your Keys.so account. See [request limits and access settings](docs/RUNTIME.md).

Authenticated HTTP is available for a server deployment. See [HTTP setup](INSTALL.md#http), [configuration and permissions](docs/RUNTIME.md) and [Python package integration](INSTALL.md#python-package-and-platform-integration).

<details>
<summary>For developers: project checks</summary>

```sh
uv sync --frozen --all-groups
uv run --frozen python scripts/verify.py
uv run --frozen python scripts/verify_install.py
```

Tests use synthetic fixtures. A passing test run does not establish live provider connectivity.

</details>

## Built by ZAI.ONE

[ZAI.ONE](https://zai.one) is a digital agency working on websites, SEO, advertising and analytics. We also build tools that connect AI assistants to everyday work. [Talk to us on Telegram](https://t.me/zai_one) about setup, automation or an integration for your team.

## Use and feedback

You may install and use this project for your own accounts under [LicenseRef-ZAI-ONE](LICENSE).
This is not an open-source license. Third-party notices remain in [NOTICE](NOTICE).
If it helps, give the repository a ⭐. Missing something or found a bug? [Open an issue](https://github.com/zai-one/keysso-mcp/issues/new/choose).
I'm working on this project; accepted improvements are implemented here. Support is not guaranteed.
