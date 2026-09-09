"""Discover the enforced report surface without sending a provider request."""

from __future__ import annotations

from typing import Any

from zai_keysso.adapter import ALLOWED_PARAMS, ALLOWED_PATHS, ALLOWED_VIEWS

PARAMETERS = {
    "domain": "DNS domain; Unicode is normalized to IDNA",
    "base": "Provider database code; 1-32 letters, digits, underscores or hyphens",
    "incl": "Comma-separated list of 1-20 domains",
    "excl": "Comma-separated list of at most 20 domains",
    "view": "One of: " + ", ".join(sorted(ALLOWED_VIEWS)),
    "page": "Page number, 1-100",
    "per_page": "Rows per page, 1-500",
    "limit": "Result limit, 1-100",
    "top": "Top limit, 1-100",
    "ads_id": "Advertisement ID, 1-2147483647",
    "sort": "Provider field followed by |asc or |desc",
}


def report_catalog() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": "keys_so_query",
        "method": "GET",
        "reports": [{"path": path} for path in sorted(ALLOWED_PATHS)],
        "path_templates": [{"path": "/report/ads/rsya/domains/{domain}", "domain": "valid DNS domain"}],
        "parameters": {key: PARAMETERS[key] for key in sorted(ALLOWED_PARAMS)},
        "parameter_scope": "Service allowlist; required parameters vary by provider report",
        "pagination": "One provider request per call; request further pages explicitly",
        "example": {
            "path": "/report/simple/domain_dashboard",
            "params": {"domain": "example.com", "base": "msk"},
        },
    }
