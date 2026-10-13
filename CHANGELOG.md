# Changelog

## Unreleased — API coverage round, semantics -> clusters -> positions, router eval

- `keys_so_query` allowlist covers the rest of the read API (apidoc.keys.so, 2026-10): competitor pages, keywords by page (`url`, `includeSubLevels`), lost pages, organic AI answers, outlinks / outlink domains, links by IP and subnet, top-domain visibility, Direct ads by phrase (`kid`), RSYA, subdomains (`id`), robots.txt history (`date`), Zen dashboard/channels/publications, projects and project competitors, saved group reports (`/report/group/list`, `/report/group/<section>/<rid>`).
- New opt-in toolsets (off by default, so the default tool list and token budget stay flat): `jobs` — `keysso_keyword_job` (keywords_by_list, extended_keywords, concurents_by_keywords: start -> status -> result) and `keysso_clustering` (create -> build -> status -> folders -> keywords); `monitoring` — `keysso_monitoring` (projects, entity, dates, report, compare, chart, limits; create from a clustering uid or phrases; start a refresh). Every start returns a free preview until `confirm=true`; `KEYSSO_READ_ONLY=1` removes them.
- Skill `keysso-semantic-core` (self-contained semantics -> clusters -> positions), guide `keysso://guide/jobs`, prompt `semantic_core`.
- Router: one line per intent (RU/EN words -> first tool; skill; guide) plus `keysso://playbook` and the generated `keysso://guide/tool-map` (every tool by toolset) as fallbacks. `KEYSSO_TOOLSETS` accepts `default` and `all`.
- `tests/test_routing_eval.py` + `tests/evals/routing_cases.json`: 18 casual RU/EN requests; fails if any tool, skill or guide is unreachable from the router.

## 0.5.0 — Agent layer, limits and column projection

- License: LicenseRef-ZAI-ONE 2.0 (source-available). Free install and use for yourself and your organisation, including commercial work; issues and pull requests welcome; copying code into other projects, redistribution, embedding and competing hosted services need written permission. Earlier releases keep their LicenseRef-ZAI-ONE 1.0 terms (see NOTICE). README first screen: one-line scope, why this MCP, maintenance and update check.
- Agent layer: router `instructions` (≤1200 chars: when Keys.so vs Topvisor/Arsenkin, quota rules), compact template descriptions and titles.
- Toolsets `meta`, `reports`, `ai_tracker` (`KEYSSO_TOOLSETS`, `KEYSSO_TOOLS`, `KEYSSO_DISABLED_TOOLS`, `KEYSSO_READ_ONLY`); `keysso://toolsets`.
- Resources `keysso://playbook`, `keysso://guide/{metrics-glossary,ai-tracker,errors}`; prompts `competitor_research`, `content_gap`, `phrase_report`.
- Self-contained skills `keysso-competitor-research`, `keysso-content-gap`, `keysso-phrase-report` with references and templates; Claude Code plugin manifest, Cursor rule, `.agents/skills`.
- New `keysso_limits` (`GET /limits/all`); `fields=[...]` column projection on `keysso_domain_report` and `keysso_compare_domains` (trims rows after fetch, so it saves tokens, not quota; part of the delegation hash only when provided; names absent from every row are listed in `missing_fields`).
- `scripts/token_budget.py` + tests gate instruction, description and SKILL.md sizes.
- Install snippets and the plugin manifest pin `git+https://github.com/zai-one/keysso-mcp@v0.5.0`.

## 0.4.0 — Ad archives, AI tracker and update hints

- `keys_so_query`: monthly Yandex ad archives from Keys.so API 1.0.24–1.0.26 (`context/ads/archive`, `context/keywords/archive`, `context/keywords/byads/archive`, `context/keyword/ads/archive` and their `months` lists) with `month`, `keyword` and `full` parameters; `keyword_dashboard` and `similarkeys` phrase reports.
- Sorts that Keys.so now rejects with HTTP 400 fail locally; up to three comma-separated sort fields are accepted.
- `keysso_ai_tracker`: read-only AI tracker reports (projects, entity, dates, report, mentions, citation, reference, sources, competitors, prompt).
- `keysso_check_update`: suggests an update from the latest GitHub release and never installs; 24h cache, offline-safe, cached startup hint, opt out with `KEYSSO_DISABLE_UPDATE_CHECK=1`.
- Update check hardening: only plain version tags (`v1.2.3`) are accepted, the cache is re-validated on read, failures back off for 30 minutes and `force_refresh` runs at most once a minute.
- `keysso_check_update` goes through the same authorization and audit as the other tools without spending Keys.so quota.
- MCP tool annotations (`readOnlyHint`, `idempotentHint`) on every tool.
- Strict input types: wrongly typed `keys_so_query` parameters fail with `validation_failed` before any provider call.

## 0.3.0 — Reports you can work with

- Typed domain reports and domain comparisons with bounded pagination, provenance and CSV export.
- Preserve per-attempt quotas across report pages and redact provider fields before CSV conversion.
- Installable setup wizard and JSON/TOML client snippets that work outside the checkout.
- English and Russian agency information, integration contact and package installation guide.

## 0.2.0

- Explicit config-file startup and offline configuration doctor.
- Install/client guide, local setup wizard and clean-wheel validation.
- Discover reports via keysso://reports and call keys_so_query with the documented path and parameters.
- LicenseRef-ZAI-ONE and Issues-based feedback policy.
