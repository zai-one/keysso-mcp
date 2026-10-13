# Domain reports and comparisons

Use `keysso_domain_report` for a named report: `keywords`, `competitors`, `pages`
or `backlinks`. Use `keysso_compare_domains` to explore overlaps or gaps between
included and excluded domains. Both use the same credentials, account boundary,
read scope, request quotas, audit and total operation deadline as `keys_so_query`.
The original raw-query tool keeps its existing schema and response.

## Examples

Keyword research:

```json
{"report":"keywords","domain":"example.com","base":"msk","sort":"pos|asc","max_pages":2,"page_size":100,"output":"json"}
```

A competitor's keywords excluding your own domain:

```json
{"include":["competitor.example"],"exclude":["example.com"],"base":"msk","view":"organic","max_pages":2,"page_size":100,"output":"csv"}
```

Comparisons follow Keys.so's `incl`/`excl` semantics; `view` is `organic`, `context`
or `backlinks`. Regional `base` applies to search reports; the domain backlinks
endpoint does not accept a regional base. API definitions: [Keys.so documentation](https://apidoc.keys.so/).

## Read completeness before interpreting results

The default is one page of 100 rows. A call may fetch at most five pages of at
most 500 rows each, within the service's page-number limit of 100 and a 256 KiB
row-data budget. Each HTTP attempt, including retries, consumes account quota.

- `source` records the report, normalized parameters, retrieval time and requested/included pages.
- `row_count` describes the returned rows; `total_reported` is the provider's total, when available.
- `complete=true` means a traversal from page one reached the declared end with consistent page metadata.
- `stop_reason` explains a page/byte limit, missing metadata, changed totals or a repeated page.
- `next_page` identifies where to continue, when supported. If a page exceeds the byte budget, reduce `page_size` and restart the traversal to avoid shifting page boundaries.

Starting at a later page never produces `complete=true`, even when it reaches the
end. Missing data is not zero. Provider pages are live reads, not an atomic snapshot;
unchanged totals cannot prove the provider's data stayed unchanged during traversal.
If a provider request fails, the call returns the normal safe provider error. It does
not return a successful partial export or automatically resume a failed traversal.

JSON preserves provider fields after secret redaction. CSV combines the returned
columns, preserves Unicode, serializes nested values as JSON and leaves missing
cells empty. String cells beginning with a formula marker are prefixed with an
apostrophe; numeric values remain numbers. Field-aware secret redaction happens
before export. `complete` describes row coverage, not unredacted field contents.

`fields=[...]` (1-30 column names) on `keysso_domain_report` and
`keysso_compare_domains` keeps only those columns in each row. The projection runs
after the pages are fetched: it shrinks the response, not the quota spent. A
requested name that occurs in none of the returned rows (for example a typo) is
listed in `missing_fields`; check column names in a first small response.

## Ad archives and phrase reports

`keys_so_query` also accepts the monthly Yandex ad archive (Keys.so API
[changelog](https://www.keys.so/ru/api-changelog) 1.0.24–1.0.26):
`/report/simple/context/ads/archive` (`full=true` adds keywords per ad),
`/report/simple/context/ads/archive/months`, `/report/simple/context/keywords/archive`,
`/report/simple/context/keywords/byads/archive` (`ads_id`),
`/report/simple/context/keyword/ads/archive` and `.../archive/months` (`keyword`).
`month` is `YYYY-MM`; without it Keys.so uses the current month. Phrase reports
`/report/simple/keyword_dashboard` and `/report/simple/similarkeys` take `keyword`.

Since 1.0.25 Keys.so answers HTTP 400 to sorting context keyword reports by
`header`, `txt` or `url`; the keyword ad archive sorts only by `keyscnt` or `serp`.
Such sorts are rejected locally before any quota is spent.

```json
{"path": "/report/simple/context/keywords/archive", "params": {"domain": "example.com", "base": "msk", "month": "2026-09", "sort": "wsk|desc"}}
```

## AI tracker

`keysso_ai_tracker` reads [AI tracker](https://apidoc.keys.so/) data with GET
requests only. Use `report=projects` to find a `tracker_id`, then `entity`, `dates`,
`report` (`date_from`/`date_to`), `mentions`, `citation`, `reference`, `sources`
(`view=url|domain`), `competitors` or `prompt` (`prompt_id` and `date`). Filter by
`systems` (AI system IDs listed in the tool description) and prompt `groups`.

## Delegated HTTP

Use the exact new tool name in the delegation's `tool` claim. Its `request_hash`
must cover the complete argument object, including defaults: `base`, `sort`
(domain reports only), `view` (comparisons only), `start_page`, `max_pages`,
`page_size` and `output`. Defaults are visible in the MCP schema. `fields` is part
of the hashed object only when the call provides it; an omitted (or null) `fields`
is not included. The nonce is
consumed once for the whole call; its pages share that execution's audit and
deadline. A raw-query delegation does not authorize a typed report.
