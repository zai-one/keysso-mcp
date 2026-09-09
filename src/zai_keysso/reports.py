"""Bounded provider report collection; never infer completeness from a short page."""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import UTC, datetime
from typing import Any

from zai_keysso.adapter import KeysSoAdapter
from zai_keysso.sanitizer import redact_literal, sanitize_provider_response
from zai_keysso.transport import ProviderResponseError

REPORT_PATHS = {
    "keywords": "/report/simple/organic/keywords",
    "competitors": "/report/simple/organic/concurents",
    "pages": "/report/simple/organic/sitepages",
    "backlinks": "/report/simple/links/backlinks",
}
MAX_BYTES = 262_144


def validate_bounds(start_page: int, max_pages: int, page_size: int, output: str) -> None:
    for value, low, high in [(start_page, 1, 100), (max_pages, 1, 5), (page_size, 1, 500)]:
        if type(value) is not int or not low <= value <= high:
            raise ValueError("report pagination is outside service limits")
    if output not in {"json", "csv"}:
        raise ValueError("unsupported report format")


def domain_request(report: str, domain: str, base: str, sort: str | None) -> tuple[str, dict]:
    if report not in REPORT_PATHS:
        raise ValueError("unsupported domain report")
    path = REPORT_PATHS[report]
    params = {"domain": domain}
    if report != "backlinks":
        params["base"] = base
    if sort is not None:
        params["sort"] = sort
    return KeysSoAdapter.validate(path, params)


def comparison_request(include: list[str], exclude: list[str], base: str, view: str) -> tuple[str, dict]:
    if not 1 <= len(include) <= 20 or len(exclude) > 20:
        raise ValueError("domain list exceeds service limits")
    # Validate each member separately so a comma cannot smuggle extra domains into a typed list.
    for domain in [*include, *exclude]:
        KeysSoAdapter.validate("/report/simple/domain_dashboard", {"domain": domain})
    params = {"incl": ",".join(include), "excl": ",".join(exclude), "base": base, "view": view}
    return KeysSoAdapter.validate("/report/compare", params)


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_export(rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    columns = sorted({key for row in rows for key in row})
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    if columns:
        writer.writerow([_csv_value(key) for key in columns])
        writer.writerows([_csv_value(row.get(key)) for key in columns] for row in rows)
    return stream.getvalue(), columns


async def collect_report(
    adapter: KeysSoAdapter,
    path: str,
    params: dict[str, Any],
    *,
    start_page: int,
    max_pages: int,
    page_size: int,
    output: str,
    secret: str = "",
) -> dict[str, Any]:
    validate_bounds(start_page, max_pages, page_size, output)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    pages: list[int] = []
    requested_pages: list[int] = []
    total: int | None = None
    last: int | None = None
    reason = "page_limit"
    complete = False
    next_page: int | None = start_page
    for page in range(start_page, min(start_page + max_pages, 101)):
        payload = await adapter.query(path, {**params, "page": page, "per_page": page_size})
        requested_pages.append(page)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ProviderResponseError("expected a paginated report")
        batch = payload["data"]
        if len(batch) > page_size or any(not isinstance(row, dict) for row in batch):
            raise ProviderResponseError("invalid report rows")
        # Preserve field-aware redaction before flattening into a CSV string.
        batch = sanitize_provider_response(batch)
        if secret:
            batch = redact_literal(batch, secret)
        fingerprint = json.dumps(batch, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if batch and fingerprint in seen:
            reason, next_page = "repeated_page", page
            break
        seen.add(fingerprint)
        if len(json.dumps(rows + batch, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
            reason, next_page = "byte_limit", page
            break
        metadata = [payload.get(key) for key in ("current_page", "per_page", "last_page", "total")]
        valid = all(_integer(item) for item in metadata)
        current, size, declared_last, declared_total = metadata
        if valid and (current != page or size != page_size):
            reason, next_page = "pagination_mismatch", page
            break
        if valid and total is not None and (total != declared_total or last != declared_last):
            reason, next_page = "report_changed", page
            break
        rows.extend(batch)
        pages.append(page)
        next_page = page + 1 if page < 100 else None
        if not valid:
            reason = "missing_pagination_metadata"
            break
        total, last = declared_total, declared_last
        expected_last = max(1, math.ceil(total / page_size))
        expected_rows = max(0, min(page_size, total - (page - 1) * page_size))
        if last not in ({0, 1} if total == 0 else {expected_last}) or len(batch) != expected_rows:
            reason = "inconsistent_pagination_metadata"
            break
        if page >= last:
            complete, reason, next_page = start_page == 1, "end_of_report", None
            break
        if page == 100:
            reason = "provider_page_cap"
    result: dict[str, Any] = {
        "source": {
            "provider": "keys.so",
            "path": path,
            "parameters": params,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "requested_pages": requested_pages,
            "included_pages": pages,
            "page_size": page_size,
        },
        "row_count": len(rows),
        "total_reported": total,
        "complete": complete,
        "stop_reason": reason,
        "next_page": next_page,
        "consistency": "live_pages_not_a_provider_snapshot",
        "format": output,
    }
    if output == "csv":
        value, columns = csv_export(rows)
        if len(value.encode("utf-8")) > MAX_BYTES:
            raise ProviderResponseError("CSV exceeds the response limit; request fewer rows")
        result.update(csv=value, columns=columns, formula_strings_escaped=True)
    else:
        result["rows"] = rows
    return result
