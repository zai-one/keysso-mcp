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

## Delegated HTTP

Use the exact new tool name in the delegation's `tool` claim. Its `request_hash`
must cover the complete argument object, including defaults: `base`, `sort`
(domain reports only), `view` (comparisons only), `start_page`, `max_pages`,
`page_size` and `output`. Defaults are visible in the MCP schema. The nonce is
consumed once for the whole call; its pages share that execution's audit and
deadline. A raw-query delegation does not authorize a typed report.
