"""Read-only Keys.so AI tracker reports (GET /ai_tracker*), typed and bounded.

Creating, editing, starting or deleting trackers, prompts and competitors is not exposed.
Reference: https://apidoc.keys.so/ (AI tracker section) and https://www.keys.so/ru/api-changelog
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# report -> (path template, accepted optional arguments)
_COMMON = frozenset({"systems", "groups"})
REPORTS: dict[str, tuple[str, frozenset[str]]] = {
    "projects": ("/ai_tracker", frozenset({"search", "page", "per_page"})),
    "entity": ("/ai_tracker/{id}/entity", frozenset()),
    "dates": ("/ai_tracker/{id}/dates", _COMMON),
    "report": (
        "/ai_tracker/{id}/report",
        _COMMON | {"date_from", "date_to", "search", "page", "per_page"},
    ),
    "mentions": ("/ai_tracker/{id}/mentions", _COMMON | {"search", "last", "page", "per_page"}),
    "citation": ("/ai_tracker/{id}/citation", _COMMON),
    "reference": ("/ai_tracker/{id}/reference", _COMMON),
    "sources": (
        "/ai_tracker/{id}/sources",
        _COMMON | {"date_from", "date_to", "view", "search", "page", "per_page"},
    ),
    "competitors": ("/ai_tracker/{id}/competitors", _COMMON | {"search", "page", "per_page"}),
    "prompt": ("/ai_tracker/{id}/prompt", frozenset({"prompt_id", "date"})),
}
KNOWN_SYSTEMS = {
    1: "GigaChat",
    3: "DeepSeek",
    5: "Perplexity",
    6: "ChatGPT",
    8: "Alice AI in Search",
    9: "Google AI Mode",
    10: "Gemini",
    11: "Claude",
    12: "Alice AI chat",
}
MAX_ID = 2_147_483_647
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _int(value: object, field: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field} must be an integer between {low} and {high}")
    return value


def _day(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"{field} must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = value.strip()
    if not 1 <= len(text) <= maximum or _CONTROL.search(text):
        raise ValueError(f"{field} must contain 1-{maximum} printable characters")
    return text


def ai_tracker_request(
    report: str,
    tracker_id: int | None = None,
    **arguments: Any,
) -> tuple[str, dict[str, Any]]:
    """Validate one AI tracker read and return (path, query params) without network access."""
    if report not in REPORTS:
        raise ValueError("unsupported AI tracker report")
    template, accepted = REPORTS[report]
    supplied = {key: value for key, value in arguments.items() if value is not None and value != []}
    unexpected = sorted(set(supplied) - accepted)
    if unexpected:
        raise ValueError(f"{report} does not accept: " + ", ".join(unexpected))
    if "{id}" in template:
        path = template.format(id=_int(tracker_id, "tracker_id", 1, MAX_ID))
    elif tracker_id is not None:
        raise ValueError("projects lists trackers and does not take tracker_id")
    else:
        path = template
    params: dict[str, Any] = {}
    if "systems" in supplied:
        systems = supplied["systems"]
        if not isinstance(systems, list) or len(systems) > 20:
            raise ValueError("systems must be a list of at most 20 AI system IDs")
        params["systems[]"] = sorted({_int(item, "systems", 1, 1000) for item in systems})
    if "groups" in supplied:
        groups = supplied["groups"]
        if not isinstance(groups, list) or len(groups) > 50:
            raise ValueError("groups must be a list of at most 50 prompt group names")
        params["groups[]"] = list(dict.fromkeys(_text(item, "groups", 255) for item in groups))
    for field in ("date_from", "date_to", "date"):
        if field in supplied:
            params[field] = _day(supplied[field], field)
    if "date_from" in params and "date_to" in params and params["date_from"] > params["date_to"]:
        raise ValueError("date_from must not be after date_to")
    if "search" in supplied:
        params["search"] = _text(supplied["search"], "search", 255)
    if "view" in supplied:
        if supplied["view"] not in {"url", "domain"}:
            raise ValueError("view must be url or domain")
        params["view"] = supplied["view"]
    if "last" in supplied:
        if not isinstance(supplied["last"], bool):
            raise ValueError("last must be a boolean")
        params["last"] = int(supplied["last"])
    if "page" in supplied:
        params["page"] = _int(supplied["page"], "page", 1, 100)
    if "per_page" in supplied:
        params["per_page"] = _int(supplied["per_page"], "per_page", 1, 500)
    if report == "prompt":
        if "prompt_id" not in supplied or "date" not in params:
            raise ValueError("prompt requires prompt_id and date")
        params["prompt_id"] = str(_int(supplied["prompt_id"], "prompt_id", 1, MAX_ID))
    return path, params
