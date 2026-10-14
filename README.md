🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Keys.so MCP

**Turn competitor data into your next SEO investigation.**

> MCP server for Keys.so (read-only by default): competitor domains, organic and paid keywords, pages, ad archives, backlinks and the AI-answer (GEO) tracker.

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
| Look back at ads | Monthly Yandex ad archives for a domain, an ad or a phrase (`month=YYYY-MM`), plus phrase dashboards and similar phrases. |
| Track AI answers (GEO) | `keysso_ai_tracker` reads your AI tracker projects: mentions, citation, brand vs competitor visibility, sources and prompt answers. Nothing is created, started or deleted. |

## Why this MCP

- Optional lazy tool loading: set `KEYSSO_TOOL_LOADING=lazy` (or choose it in the setup wizard) to start with a small core and enable toolsets on demand; see [Lazy tool loading](#lazy-tool-loading).
- Read-only by default: the default toolsets never create, start or delete anything. Opt-in toolsets (`jobs`, `monitoring`, `api`) can start limit-spending jobs and change monitoring projects, and each such call needs an operator-accepted `approval_id`.
- A small tool surface routes to the documented report catalog (`keysso://reports`), with limits and field filtering to keep responses short.
- Toolsets (default: meta, reports, ai_tracker; opt-in: jobs, monitoring, api), router instructions that say when to use Keys.so vs Topvisor or Arsenkin, skills and prompts.
- The other Keys.so MCP on GitHub ([perfilev/keys-so-mcp](https://github.com/perfilev/keys-so-mcp), 21 tools) has no tests, CI or update check.

## Lazy tool loading

Optional lazy tool loading: `KEYSSO_TOOL_LOADING=lazy` starts with a small core plus `keysso_enable_toolsets` and adds toolsets on demand (`tools/list_changed`). Startup cost (tools/list + instructions, ≈chars/4): eager ≈1726 tokens, lazy ≈1013 tokens (−41%). Default `eager` is unchanged; if your client ignores `tools/list_changed`, keep `eager` or reconnect after enabling. Scope: enablement is per MCP session (FastMCP session visibility), so one client's enabled toolsets never appear for another. The HTTP transport here is stateless (every request is its own session), so enabled toolsets do not persist there: for shared HTTP use `eager` or `KEYSSO_TOOLSETS`.

Clients and `notifications/tools/list_changed` (verified against official docs, changelogs or maintainer statements, 2026-10):

| Client | `tools/list_changed` | Source |
|---|---|---|
| Claude Code | Supported (interactive: tools, prompts, resources; `-p`/Agent SDK: tools) | [docs: Dynamic tool updates](https://code.claude.com/docs/en/mcp) |
| VS Code (GitHub Copilot) | Supported (dynamic tool discovery); new tools may reach the agent only on the next turn | [docs](https://code.visualstudio.com/api/extension-guides/ai/mcp), [#303012](https://github.com/microsoft/vscode/issues/303012) |
| Gemini CLI | Supported (refreshes the tool registry) | [PR #14375](https://github.com/google-gemini/gemini-cli/pull/14375), [PR #21050](https://github.com/google-gemini/gemini-cli/pull/21050) |
| Cursor | Unreliable: staff confirm a regression in 3.12.x; restart Cursor after enabling | [forum](https://forum.cursor.com/t/mcp-server-regression-does-not-reload-tools-disconnect-does-nothing-ignores-mcp-json-changes-etc/166216) |
| Claude Desktop, Windsurf, Codex CLI, Cline, Zed, Continue | Unverified: no official statement found; use `eager` or reconnect after enabling | — |

## Maintained and up to date

- Actively maintained by ZAI.ONE: current version 0.5.0; release notes in [CHANGELOG.md](CHANGELOG.md) and [Releases](https://github.com/zai-one/keysso-mcp/releases).
- Built-in update check: ask the assistant to run `keysso_check_update` (public GitHub API, no credentials, cached; nothing is installed automatically; `KEYSSO_DISABLE_UPDATE_CHECK=1` turns it off).
- Follows current MCP practice: tool annotations (read-only / destructive hints), toolsets and read-only mode, server `instructions`, prompts and resources, structured errors with recovery hints, secrets kept out of tool output, a token budget for tool descriptions enforced in tests.
- CI runs the test suite on Linux and Windows for every pull request.

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


<!-- agent-block:start -->
## Install in your agent

Run `keysso-mcp` straight from GitHub with [uv](https://docs.astral.sh/uv/). Pin a release tag (`@vX.Y.Z`) for
reproducible installs; placeholders below are examples, keep secrets in files outside the repo.

**Claude Code**

```bash
claude mcp add keysso --env KEYSSO_API_TOKEN_FILE=/path/to/keysso.token --env KEYSSO_STATE_PATH=/path/to/keysso.sqlite -- uvx --from git+https://github.com/zai-one/keysso-mcp@v0.5.0 keysso-mcp
```

Skills for Claude Code: copy `skills/*` into `~/.claude/skills/` (or install this repo as a plugin — it
ships `.claude-plugin/plugin.json` with the skills and the MCP server).

**Cursor** — `.cursor/mcp.json` ([one-click install](cursor://anysphere.cursor-deeplink/mcp/install?name=keysso&config=eyJjb21tYW5kIjogInV2eCIsICJhcmdzIjogWyItLWZyb20iLCAiZ2l0K2h0dHBzOi8vZ2l0aHViLmNvbS96YWktb25lL2tleXNzby1tY3BAdjAuNS4wIiwgImtleXNzby1tY3AiXSwgImVudiI6IHsiS0VZU1NPX0FQSV9UT0tFTl9GSUxFIjogIi9wYXRoL3RvL2tleXNzby50b2tlbiIsICJLRVlTU09fU1RBVEVfUEFUSCI6ICIvcGF0aC90by9rZXlzc28uc3FsaXRlIn19)):

```json
{
  "mcpServers": {
    "keysso": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/zai-one/keysso-mcp@v0.5.0",
        "keysso-mcp"
      ],
      "env": {
        "KEYSSO_API_TOKEN_FILE": "/path/to/keysso.token",
        "KEYSSO_STATE_PATH": "/path/to/keysso.sqlite"
      }
    }
  }
}
```

**Codex** — `~/.codex/config.toml` (skills: copy `skills/*` into `~/.codex/skills/`, or keep the
repo's `.agents/skills` link):

```toml
[mcp_servers.keysso]
command = "uvx"
args = ["--from", "git+https://github.com/zai-one/keysso-mcp@v0.5.0", "keysso-mcp"]
env = { KEYSSO_API_TOKEN_FILE = "/path/to/keysso.token", KEYSSO_STATE_PATH = "/path/to/keysso.sqlite" }
```

**Claude Desktop** — `claude_desktop_config.json`: the same `mcpServers` block as Cursor.

## Skills (agent playbooks)

Each skill is a self-contained folder `skills/<name>/` (`SKILL.md` + its own `references/`,
`templates/`); copy the folder and it works. Agents load the short `SKILL.md` only when the task matches
and open the other files on demand. Clients without skills get the same flows as MCP prompts and the
`keysso://playbook` / `keysso://guide/{topic}` resources.

| Skill | What it does |
|---|---|
| `keysso-competitor-research` | Domain dashboard, competitors, keyword gap, top pages and ads (quota-aware). |
| `keysso-content-gap` | Phrases competitors rank for and you do not, grouped into topics. |
| `keysso-phrase-report` | One phrase: frequency, similar phrases, who ranks and advertises. |
| `keysso-semantic-core` | Semantics -> clusters -> positions inside Keys.so: expand seeds, check frequencies, cluster by SERP, monitor positions. |

## Toolsets and read-only mode

Default: `meta`, `reports`, `ai_tracker`. Opt-in (heavy, spend plan limits, need `confirm=true`):
`jobs` (`keysso_keyword_job`: mass phrase check, semantic expansion, competitor share; `keysso_clustering`)
and `monitoring` (`keysso_monitoring`: position projects, reports, compare, create from clusters, refresh),
and `api` (`keysso_api`: documented `tools/*`, `wordstat/*`, `serp/*`, clustering import/update-frequency/node keywords,
monitoring PATCH/DELETE/link-words). Every limit-spending or writing call (`confirm=true` jobs, non-GET `keysso_api` and `GET serp/<id>/csv`)
returns an `approval_id` and an `operator_command`; the operator reviews the exact request with
`keysso-approval --path FILE --list` and accepts it outside MCP with the returned
`keysso-approval --path FILE --approval-id ID --digest D --accept`,
then the agent repeats the same call with `approval_id` (single use, 30 min, same principal and account; `provider_outcome_unknown` means check the provider state before asking again).
`KEYSSO_TOOLSETS=default,jobs,monitoring`, `all`, or a comma list (see `keysso://toolsets`, `keysso://guide/tool-map`); `KEYSSO_TOOLS=a,b` adds single tools,
`KEYSSO_DISABLED_TOOLS=a,b` removes them, `KEYSSO_READ_ONLY=1` removes every write/paid tool.

## Example requests

- Кто основные конкуренты example.ru в Яндексе Москва?
- Найди запросы, по которым конкуренты есть в ТОП, а мы нет.
- Сделай отчёт по фразе «купить диван» в Санкт-Петербурге.
- Кто рекламируется по нашей тематике и с какими объявлениями?
- Как часто бренд упоминается в ответах ChatGPT и Алисы?
- Сколько лимитов Keys.so осталось?
- Собери семантику по «натяжные потолки», кластеризуй и поставь на мониторинг позиций.
<!-- agent-block:end -->

## Access and limits

Use `keysso_domain_report` for keywords, competitors, pages or backlinks, and `keysso_compare_domains` for overlaps and gaps. Each can collect up to five pages and return JSON or CSV with source and completeness fields. The original `keys_so_query` still requests one page. [Report examples and limits](docs/REPORTS.md).

Ask: “Export a competitor’s keywords excluding my domain, in CSV. Show whether the sample is complete.”

### Updates

`keysso_check_update` compares the installed version with the latest [GitHub release](https://github.com/zai-one/keysso-mcp/releases) and returns the release link and the matching `uv tool install --force ...` command. It never installs anything and uses no Keys.so quota. The result is cached for 24 hours next to the state database; when a newer release is cached, the server instructions mention it once. After a failed request it waits 30 minutes, and `force_refresh` works at most once a minute. Set `KEYSSO_DISABLE_UPDATE_CHECK=1` to turn off both the tool's network request and the startup refresh.

The default toolsets expose read-only reports; opt-in toolsets are described in [Toolsets](#toolsets-and-read-only-mode). Available data and request limits depend on your Keys.so account. See [request limits and access settings](docs/RUNTIME.md).

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

## License, use and contributing

- **Use:** you may install and use this MCP server freely for yourself and your organisation, including commercial work. If it helps, please consider giving the repository a ⭐ — appreciated, never required.
- **Contribute:** [issues](https://github.com/zai-one/keysso-mcp/issues/new/choose) and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Never post tokens, cookies, sessions or account data.
- **Not allowed without written permission from ZAI.ONE:** copying code into other projects, forking for redistribution, embedding the server in other products or offering it as a competing service.
- License: [LicenseRef-ZAI-ONE 2.0](LICENSE) (source-available, not open source). Third-party notices and license history: [NOTICE](NOTICE).
