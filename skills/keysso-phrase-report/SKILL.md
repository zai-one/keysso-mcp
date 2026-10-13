---
name: keysso-phrase-report
description: Report on one search phrase with Keys.so - frequency, similar phrases, who ranks in TOP and who advertises. Use for "отчёт по фразе", "частотность и конкуренты по запросу", "phrase research".
license: LicenseRef-ZAI-ONE
compatibility: Requires keysso-mcp.
metadata:
  service: keysso
---
# Phrase report

Glossary: [references/metrics-glossary.md](references/metrics-glossary.md).

## Steps
1. Confirm phrase and base (default msk).
2. `keys_so_query("/report/simple/keyword_dashboard", {"keyword": P, "base": B})` → frequencies
   (`ws`, `wsk`), ranking domains, ads.
3. `keys_so_query("/report/simple/similarkeys", {"keyword": P, "base": B, "per_page": 25})` → related
   phrases sorted by frequency.
4. Optional ads history: `/report/simple/context/keyword/ads/archive` with `keyword`.
5. Output: short summary (demand, competition, ad pressure), table of top 10 domains, table of 15
   similar phrases with `ws`/`wsk`, 2–3 recommendations.

## Guardrails
- 3–4 requests total; ask before paging further. Errors: [references/errors.md](references/errors.md).
