# Changelog

## Unreleased

- `keys_so_query`: monthly Yandex ad archives from Keys.so API 1.0.24–1.0.26 (`context/ads/archive`, `.../months`, `context/keywords/archive`, `context/keywords/byads/archive`, `context/keyword/ads/archive`, `.../months`) with `month`, `keyword` and `full` parameters; `keyword_dashboard` and `similarkeys`.
- Sorts that Keys.so now rejects with HTTP 400 (context keywords by `header`/`txt`/`url`, 1.0.25) fail locally; up to three comma-separated sort fields are accepted.
- `keysso_ai_tracker`: read-only AI tracker reports (projects, entity, dates, report, mentions, citation, reference, sources, competitors, prompt).
- `keysso_check_update`: suggests an update from the latest GitHub release (24h cache, offline-safe, never installs); cached startup hint; opt out with `KEYSSO_DISABLE_UPDATE_CHECK=1`.
- MCP tool annotations (`readOnlyHint`, `idempotentHint`) on every tool.
- Update check hardening: only plain version tags (`v1.2.3`) reach the result, cache or server instructions, and the cache is re-validated on read; every fetch attempt is recorded, a failure backs off for 30 minutes and `force_refresh` runs at most once a minute (also without a cache); the startup refresh follows the same rules.
- `keysso_check_update` now goes through the same authorization and audit as the other tools (account binding, request-bound delegation, ledger row) without spending Keys.so quota; `idempotentHint` is now false because a forced refresh can rewrite the cache.
- `keys_so_query`: wrongly typed `keyword`, `base`, `full` and other string parameters fail with `validation_failed` before any provider call instead of being stringified or reported as `operation_failed`.
- `KEYSSO_DISABLE_UPDATE_CHECK` is documented in `.env.example` and `docs/RUNTIME.md`; tests disable the update check by default.

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
