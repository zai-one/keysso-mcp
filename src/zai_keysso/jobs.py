"""Keys.so keyword jobs, clustering and position monitoring (opt-in toolsets).

Sources: https://apidoc.keys.so/ sections "Инструменты" (keywords_by_list, extended_keywords,
concurents_by_keywords), "Кластеризация" and "Мониторинг позиций". Every start spends plan
limits, so start actions need confirm=true after the user saw keysso_limits; reads are free of
side effects. Deleting projects, moving phrases and editing monitoring settings are not exposed.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

MAX_PHRASES = 1000
MAX_PHRASE_CHARS = 100
_UID = re.compile(r"[A-Za-z0-9:_-]{1,128}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BASE = re.compile(r"[a-z0-9_-]{1,32}\Z")
_SORT = re.compile(r"[a-zA-Z0-9_]{1,64}\|(asc|desc)\Z")

# kind -> (start path, state path or None, result path)
KEYWORD_JOBS: dict[str, tuple[str, str | None, str]] = {
    "keywords_by_list": ("/tools/keywords_by_list", None, "/tools/keywords_by_list/{uid}"),
    "extended_keywords": (
        "/tools/extended_keywords",
        "/tools/extended_keywords/state/{uid}",
        "/tools/extended_keywords/{uid}",
    ),
    "concurents_by_keywords": (
        "/tools/concurents_by_keywords",
        "/tools/concurents_by_keywords/state/{uid}",
        "/tools/concurents_by_keywords/{uid}",
    ),
}
CONFIRM_HINT = (
    "This start spends Keys.so plan limits. Call keysso_limits, show the remaining limit and the "
    "phrase count to the user, then repeat with confirm=true after an explicit OK."
)

Request = tuple[str, str, dict[str, Any], dict[str, Any] | None]


def _uid(value: object) -> str:
    if not isinstance(value, str) or _UID.fullmatch(value) is None:
        raise ValueError("uid must be the identifier Keys.so returned (letters, digits, : _ -)")
    return value


def _int(value: object, field: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field} must be an integer between {low} and {high}")
    return value


def _base(value: object) -> str:
    if not isinstance(value, str) or _BASE.fullmatch(value.strip().lower()) is None:
        raise ValueError("base is not allowed")
    return value.strip().lower()


def phrases_list(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PHRASES:
        raise ValueError(f"phrases must be a list of 1-{MAX_PHRASES} search phrases")
    clean: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("phrases must be strings")
        text = " ".join(item.split())
        if not 1 <= len(text) <= MAX_PHRASE_CHARS or _CONTROL.search(text):
            raise ValueError(f"each phrase must contain 1-{MAX_PHRASE_CHARS} printable characters")
        clean.append(text)
    return list(dict.fromkeys(clean))


def _paging(page: int | None, per_page: int | None, sort: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = _int(page, "page", 1, 100)
    if per_page is not None:
        params["per_page"] = _int(per_page, "per_page", 1, 500)
    if sort is not None:
        if not isinstance(sort, str) or _SORT.fullmatch(sort.strip()) is None:
            raise ValueError("sort must use field|asc or field|desc")
        params["sort"] = sort.strip()
    return params


def keyword_job_request(
    kind: str,
    action: str,
    *,
    phrases: list[str] | None = None,
    base: str = "msk",
    uid: str | None = None,
    top: int | None = None,
    view: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    sort: str | None = None,
    similarity: int | None = None,
) -> Request:
    if kind not in KEYWORD_JOBS:
        raise ValueError("kind must be one of: " + ", ".join(KEYWORD_JOBS))
    start, state, result = KEYWORD_JOBS[kind]
    if action == "start":
        payload: dict[str, Any] = {"list": phrases_list(phrases), "base": _base(base)}
        if kind == "concurents_by_keywords":
            if top is not None and top not in (10, 50):
                raise ValueError("top must be 10 or 50")
            payload["top"] = top or 10
        if similarity is not None:
            if kind != "extended_keywords":
                raise ValueError("similarity applies to extended_keywords only")
            # apidoc: config {similarity 5..100, deleteDuplicate, additions}
            payload["config"] = {
                "similarity": _int(similarity, "similarity", 5, 100),
                "deleteDuplicate": True,
                "additions": False,
            }
        return "POST", start, {}, payload
    if action == "status":
        if state is None:
            # keywords_by_list has no state endpoint: the result call answers while processing.
            return "GET", result.format(uid=_uid(uid)), {"base": _base(base), "per_page": 1}, None
        return "GET", state.format(uid=_uid(uid)), {}, None
    if action == "result":
        params = _paging(page, per_page, sort)
        if kind in {"keywords_by_list", "concurents_by_keywords"}:
            params["base"] = _base(base)
        if view is not None:
            # apidoc GET /tools/concurents_by_keywords/<uid>: view=organic|context (default organic)
            if kind != "concurents_by_keywords" or view not in {"organic", "context"}:
                raise ValueError("view applies to concurents_by_keywords: organic or context")
            params["view"] = view
        return "GET", result.format(uid=_uid(uid)), params, None
    raise ValueError("action must be start, status or result")


def _top_number(value: object) -> int:
    if value not in (10, 20, 50) or type(value) is not int:
        raise ValueError("top_number must be 10, 20 or 50")
    return value


def clustering_request(
    action: str,
    *,
    phrases: list[str] | None = None,
    base: str = "msk",
    uid: str | None = None,
    folder_id: int | None = None,
    top_number: int = 10,
    strength: int | None = None,
    min_frequency: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    sort: str | None = None,
) -> Request:
    if action == "list":
        return "GET", "/clustering/list", _paging(page, per_page, sort), None
    if action == "create":
        return "POST", "/clustering", {}, {"list": phrases_list(phrases), "base": _base(base)}
    if action == "build":
        payload: dict[str, Any] = {
            "topNumber": _top_number(top_number),
            "isSerpProject": True,
            "isWsProject": True,
        }
        if strength is not None:
            payload["fStrength"] = _int(strength, "strength", 1, 100)
        if min_frequency is not None:
            payload.update(fIsWsk=True, fWsk=_int(min_frequency, "min_frequency", 0, 10_000_000))
        return "POST", f"/clustering/{_uid(uid)}/build", {}, payload
    if action == "status":
        return "GET", f"/clustering/state/{_uid(uid)}", {}, None
    if action == "folders":
        return "GET", f"/clustering/node/{_uid(uid)}", {}, None
    if action == "keywords":
        folder = _int(folder_id, "folder_id", -2, 2_147_483_647)
        return "GET", f"/clustering/node/{_uid(uid)}/{folder}/keywords", _paging(page, per_page, sort), None
    raise ValueError("action must be list, create, build, status, folders or keywords")


def _day(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"{field} must use YYYY-MM-DD")
    date.fromisoformat(value)
    return value


MONITORING_REPORTS = ("projects", "entity", "dates", "report", "compare", "chart", "limits")
MONITORING_WRITES = ("create", "start")
_DOMAINISH = re.compile(r"[A-Za-z0-9.-]{1,253}(/[^\s]{0,1024})?\Z")


def monitoring_write_request(
    action: str,
    *,
    project_id: int | None = None,
    tracking_item: str | None = None,
    cluster_uid: str | None = None,
    phrases: list[str] | None = None,
    region_id: int = 213,
    engine: int = 0,
    name: str | None = None,
    folder_ids: list[int] | None = None,
) -> Request:
    """create: a monitoring project from a clustering uid or phrases; start: paid position refresh."""
    setting = {
        "regionId": _int(region_id, "region_id", 1, 10_000_000),
        "engine": _int(engine, "engine", 0, 1),
    }
    if action == "create":
        if not isinstance(tracking_item, str) or _DOMAINISH.fullmatch(tracking_item.strip()) is None:
            raise ValueError("tracking_item must be a domain or URL")
        payload: dict[str, Any] = {
            "trackingItem": tracking_item.strip(),
            "trackSubDomains": False,
            "searchSettings": [setting],
        }
        if cluster_uid is not None:
            payload["clusterUuid"] = _uid(cluster_uid)
        else:
            payload["keywords"] = phrases_list(phrases)
        if name is not None:
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 255 or _CONTROL.search(name):
                raise ValueError("name must contain 1-255 printable characters")
            payload["name"] = name.strip()
        return "POST", "/monitoring", {}, payload
    if action == "start":
        pid = _int(project_id, "project_id", 1, 2_147_483_647)
        payload = {"serp": True, "searchSettings": [setting]}
        if folder_ids:
            payload["aids"] = [_int(item, "folder_ids", -2, 2_147_483_647) for item in folder_ids[:100]]
        return "POST", f"/monitoring/{pid}/start", {}, payload
    raise ValueError("action must be create or start")


def monitoring_request(
    report: str,
    *,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    region_id: int | None = None,
    engine: int | None = None,
    folder_ids: list[int] | None = None,
    search: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    sort: str | None = None,
) -> Request:
    if report not in MONITORING_REPORTS:
        raise ValueError("report must be one of: " + ", ".join(MONITORING_REPORTS))
    params = _paging(page, per_page, sort)
    if search is not None:
        if not isinstance(search, str) or not 1 <= len(search.strip()) <= 255 or _CONTROL.search(search):
            raise ValueError("search must contain 1-255 printable characters")
        params["search"] = search.strip()
    if report == "projects":
        return "GET", "/monitoring", params, None
    pid = _int(project_id, "project_id", 1, 2_147_483_647)
    if region_id is not None or engine is not None:
        setting = {
            "regionId": _int(region_id, "region_id", 1, 10_000_000),
            "engine": _int(engine or 0, "engine", 0, 1),
        }
        params["searchSettings[]"] = [json.dumps(setting, separators=(",", ":"))]
    if folder_ids:
        if not isinstance(folder_ids, list) or len(folder_ids) > 100:
            raise ValueError("folder_ids must be at most 100 cluster folder IDs")
        key = "aids[]" if report == "limits" else "aids"
        params[key] = [_int(item, "folder_ids", -2, 2_147_483_647) for item in folder_ids]
    if report in {"report", "compare", "chart"}:
        if date_from is None or date_to is None:
            raise ValueError(f"{report} requires date_from and date_to")
        params["dateFrom"], params["dateTo"] = _day(date_from, "date_from"), _day(date_to, "date_to")
        if params["dateFrom"] > params["dateTo"]:
            raise ValueError("date_from must not be after date_to")
    suffix = {
        "entity": "entity",
        "dates": "dates",
        "report": "report",
        "compare": "report-compare",
        "chart": "report-chart",
        "limits": "limits",
    }[report]
    return "GET", f"/monitoring/{pid}/{suffix}", params, None
