---
name: keysso-competitor-research
description: Competitor research with Keys.so - domain dashboard, top competitors, keyword gap, top pages and ads, quota-aware. Use for "анализ конкурентов", "competitor analysis", "кто конкуренты сайта", "Keys.so отчёт по домену".
license: LicenseRef-ZAI-ONE
compatibility: Requires the keysso-mcp server (tools keysso_*, keys_so_query).
metadata:
  service: keysso
---
# Keys.so competitor research

Every report page spends plan requests: keep `max_pages=1` and use `fields`.
Field meanings: [references/metrics-glossary.md](references/metrics-glossary.md).

## Steps
1. Confirm domain and `base` (default msk). Optionally `keysso_limits`.
2. Overview: `keys_so_query("/report/simple/domain_dashboard", {"domain": D, "base": B})`.
3. Competitors: `keysso_domain_report(report="competitors", domain=D, page_size=10)`; take top 3–5
   (skip marketplaces/aggregators unless the user wants them).
4. Gap: for the top 3, `keysso_compare_domains(include=[C], exclude=[D], page_size=50,
   fields=["word","ws","wsk","pos"])` (check actual column names in the first response).
5. Pages: `keysso_domain_report(report="pages", domain=C, page_size=10)` for the strongest competitor.
6. Ads: `keys_so_query("/report/simple/context/ads", {"domain": C, "base": B, "per_page": 10})`.
7. Fill [templates/competitor-report.md](templates/competitor-report.md); state pages spent.

## Guardrails
- `complete=false` → say "partial"; offer `next_page`, don't auto-fetch more.
- Errors: [references/errors.md](references/errors.md).
