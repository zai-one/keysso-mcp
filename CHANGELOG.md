# Changelog

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
