"""Allowlisted Keys.so endpoints beyond the typed tools (apidoc.keys.so OpenAPI).

GET calls are reads. Every POST/PATCH/DELETE either spends plan limits (tools/*, wordstat, serp,
clustering) or changes saved data (monitoring PATCH/DELETE/link-words, deletes), so they run only
after an operator approval (see zai_keysso.approvals).
"""

from __future__ import annotations

import re
from typing import Any

_UID = r"[A-Za-z0-9_:.-]{1,64}"
_ID = r"[0-9]{1,12}"


def _p(template: str) -> re.Pattern[str]:
    return re.compile(template.replace("<uid>", _UID).replace("<id>", _ID) + r"$")


ENDPOINTS: dict[str, tuple[str, ...]] = {
    "GET": (
        "/tools/extended_keywords/state/<uid>",
        "/tools/extended_keywords/<uid>",
        "/tools/keywords_by_list/<uid>",
        "/tools/concurents_by_keywords/state/<uid>",
        "/tools/concurents_by_keywords/<uid>",
        "/tools/site-themes",
        "/tools/keywords_by_pages/weight/<uid>",
        "/tools/keywords_by_pages/pages/<uid>",
        "/tools/dictionary-ext-by-page/state/<uid>",
        "/tools/dictionary-ext-by-page/<uid>",
        "/tools/dictionary-by-pages/state/<uid>",
        "/tools/dictionary-by-pages/<uid>",
        "/wordstat/list",
        "/wordstat/get-projects-completed",
        "/wordstat/get-project-status",
        "/wordstat/report",
        "/serp",
        "/serp/<id>",
        "/serp/<id>/status",
        "/serp/<id>/csv",
        "/serp/<id>/csv/export-status",
        "/serp/<id>/competitor-domains",
        "/serp/<id>/competitor-pages",
        "/clustering/node/<uid>",
        "/monitoring/state",
    ),
    "POST": (
        "/tools/delete_double",
        "/tools/keywords_by_pages",
        "/tools/dictionary-ext-by-page",
        "/tools/dictionary-by-pages",
        "/tools/domains-batch",
        "/tools/history-serp",
        "/tools/check-top",
        "/tools/check-top-concurents-domains",
        "/tools/check-top-concurents-urls",
        "/tools/compare",
        "/tools/combine",
        "/tools/unique",
        "/tools/suggest",
        "/wordstat/create-project",
        "/wordstat/<id>/update-project",
        "/wordstat/<id>/update-words",
        "/serp",
        "/serp/<id>/update",
        "/clustering/<uid>/update-frequency",
        "/clustering/<uid>/import/list",
        "/clustering/node/<uid>/<id>/keywords",
        "/monitoring/<id>/link-words",
    ),
    "PATCH": ("/monitoring/<id>",),
    "DELETE": (
        "/wordstat/delete-project",
        "/wordstat/delete-words",
        "/serp/<id>",
        "/clustering/<uid>",
        "/monitoring/<id>",
    ),
}
_COMPILED = {method: [_p(t) for t in templates] for method, templates in ENDPOINTS.items()}
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}(\[\])?")
MAX_BODY_ITEMS = 10_000


def _scalar(value: Any, field: str) -> Any:
    if isinstance(value, bool | int | float):
        return value
    if (
        isinstance(value, str)
        and len(value) <= 20_000
        and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value)
    ):
        return value
    raise ValueError(f"{field} must be a number, boolean or printable string")


def _not_allowed(method: str) -> str:
    # There is no separate guide page: name the allowed templates so the agent can self-correct.
    allowed = ", ".join(ENDPOINTS.get(method, ())) or "methods are GET, POST, PATCH, DELETE"
    return f"Keys.so endpoint is not in the documented allowlist; allowed {method}: {allowed}"


def validate_call(
    method: str, path: str, params: dict[str, Any] | None, body: Any
) -> tuple[str, str, dict[str, Any], Any]:
    method = str(method).upper().strip()
    path = "/" + str(path).strip().lstrip("/")
    if method not in _COMPILED or not any(p.match(path) for p in _COMPILED[method]):
        raise ValueError(_not_allowed(method))
    if any(segment in {".", ".."} for segment in path.split("/")):
        # HTTP clients collapse dot segments, so /tools/extended_keywords/.. would reach /tools.
        raise ValueError(_not_allowed(method))
    clean: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError("invalid query parameter name")
        if isinstance(value, list):
            if len(value) > 100:
                raise ValueError(f"{key}: at most 100 values")
            clean[key] = [_scalar(v, key) for v in value]
        else:
            clean[key] = _scalar(value, key)
    if method == "GET" and body is not None:
        raise ValueError("GET takes no body")
    if body is not None:
        if not isinstance(body, dict | list):
            raise ValueError("body must be a JSON object or array")
        items = (
            body if isinstance(body, list) else next((v for v in body.values() if isinstance(v, list)), [])
        )
        if len(items) > MAX_BODY_ITEMS:
            raise ValueError(f"body lists are limited to {MAX_BODY_ITEMS} items")
    return method, path, clean, body


def needs_approval(method: str) -> bool:
    return method != "GET"
