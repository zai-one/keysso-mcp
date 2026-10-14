---
name: keysso-semantic-core
description: Semantics -> clusters -> positions in Keys.so alone - expand seed phrases, check frequencies, cluster by SERP, create position monitoring. Use for "собери семантику", "кластеризуй ядро", "semantic core", "отслеживать позиции кластеров".
license: LicenseRef-ZAI-ONE
compatibility: Requires keysso-mcp with KEYSSO_TOOLSETS=default,jobs,monitoring (or all). Self-contained - no other MCP needed.
metadata:
  service: keysso
---
# Semantic core: semantics -> clusters -> positions

Flow table and limits: [references/jobs.md](references/jobs.md). Errors: [references/errors.md](references/errors.md).

## Steps
1. Ask for domain, 3–20 seed phrases, base (`msk` default) and region (213 Москва).
2. `keysso_limits`; tell the user the phrase count and what each start spends. Ask for OK.
3. Semantics: `keysso_keyword_job(kind="extended_keywords", action="start", phrases=seeds, confirm=true)`;
   poll `action="status"`, then `action="result", sort="wsk|desc", per_page=500` (up to 3 pages).
   Optional: add the site's own phrases via `keysso_domain_report(report="keywords")`.
4. Clean: drop `wsk` < 10, duplicates, foreign brands, off-topic words; keep ≤ 1000 phrases.
   If frequencies are missing, run `kind="keywords_by_list"` on the cleaned list.
5. Clusters: `keysso_clustering(action="create", phrases, confirm=true)` -> `action="build", uid,
   top_number=10, confirm=true` -> poll `status` -> `folders` -> `keywords` per folder.
6. Map each cluster to a page: existing URL (from `report="pages"`) or "new page".
7. Positions: `keysso_monitoring(action="create", tracking_item=domain, cluster_uid=uid,
   region_id=213, confirm=true)`, `action="limits"`, `action="start", confirm=true`, then
   `action="report", date_from, date_to` and later `action="compare"`.
8. Output with [templates/semantic-core.md](templates/semantic-core.md).

## Guardrails
- Every `confirm=true` call first returns `approval_id` + `operator_command`; show it, wait until the
  operator runs it (never run it yourself), then repeat the same call with `approval_id`.
- Other documented endpoints (wordstat, serp, tools/*, clustering import, monitoring PATCH/DELETE):
  `keysso_api` (toolset `api`), same approval rule for every non-GET.
- Never pass `confirm=true` without the user's explicit OK for that start.
- Jobs are async: report `uid`s so the user can resume; never restart a job just to poll.
- Partial results stay partial: say which steps did not finish.
