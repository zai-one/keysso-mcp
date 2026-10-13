---
name: keysso-content-gap
description: Keyword/content gap - phrases competitors rank for but my site does not, grouped into topics with page suggestions. Use for "контент-гэп", "чего нет на сайте", "keyword gap", "упущенные запросы".
license: LicenseRef-ZAI-ONE
compatibility: Requires keysso-mcp. Optional - arsenkin-mcp for SERP clustering of the gap list.
metadata:
  service: keysso
---
# Content gap

Glossary: [references/metrics-glossary.md](references/metrics-glossary.md).

## Steps
1. Get `my_domain`, 1–5 competitors (or find them via `keysso_domain_report(report="competitors")`), base.
2. `keysso_compare_domains(include=competitors, exclude=[my_domain], page_size=100, max_pages=1-3)`.
3. Drop phrases with tiny exact frequency (`wsk` < 10) and brand terms of competitors.
4. Group into topics by shared head words (or, if arsenkin-mcp is connected and the user approves its
   cost, run skill `arsenkin-serp-clustering` on the list).
5. For each topic: example phrases, sum of `wsk`, competitor URL (from `report="pages"` if needed),
   action: new page vs improve existing.
6. Output with [templates/content-gap.md](templates/content-gap.md).

## Guardrails
- Report partial data honestly (`complete`, `stop_reason`). Errors: [references/errors.md](references/errors.md).
