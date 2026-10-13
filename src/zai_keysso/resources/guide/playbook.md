# Keys.so playbook

Keys.so = market data on any domain or phrase (Yandex/Google regional bases). Read-only; each report
page spends plan requests.

1. **Budget** — `keysso_limits` before multi-page pulls; default `max_pages=1`, `page_size` 25–100,
   `fields=[...]` to keep only needed columns (trims the response after fetch: saves tokens, not
   quota).
2. **Domain** — `keys_so_query("/report/simple/domain_dashboard", {domain, base})` for the overview
   (vis, it1/it3/it10/it50, keys, concs, pages, ads), then `keysso_domain_report(report=...)`.
3. **Competitors / gap** — `keysso_domain_report(report="competitors")`, then
   `keysso_compare_domains(include=[competitor], exclude=[my_site])`.
4. **Phrase** — `/report/simple/keyword_dashboard` and `/report/simple/similarkeys` with `keyword`.
5. **Ads** — `/report/simple/context/ads`, `/report/simple/context/keywords`, archive by `month`.
6. **AI answers (GEO)** — `keysso_ai_tracker` (see `keysso://guide/ai-tracker`).

Bases: `msk` Яндекс Москва (default), `spb`, `ekb`, … `gru` Google Москва, `zen` Дзен — full list in
`keysso://guide/metrics-glossary`. All report paths/params: `keysso://reports`.
Skills: `keysso-competitor-research`, `keysso-phrase-report`, `keysso-content-gap`.
