from __future__ import annotations

import re
from datetime import date
from typing import Any, Protocol

from zai_keysso import __version__
from zai_keysso.ai_tracker import ai_tracker_request
from zai_keysso.coalescing import AsyncSingleFlight
from zai_keysso.transport import JsonHttpClient, ProviderError, request_hash

LIMITS_PATH = "/limits/all"
ALLOWED_PATHS = frozenset(
    {
        "/limits/all",
        "/report/compare",
        "/report/simple/context/ads",
        "/report/simple/context/ads/archive",
        "/report/simple/context/ads/archive/months",
        "/report/simple/context/ads/facts",
        "/report/simple/context/ads/links",
        "/report/simple/context/concurents",
        "/report/simple/context/keyword/ads/archive",
        "/report/simple/context/keyword/ads/archive/months",
        "/report/simple/context/keywords",
        "/report/simple/context/keywords/archive",
        "/report/simple/context/keywords/byads",
        "/report/simple/context/keywords/byads/archive",
        "/report/simple/direct/domain",
        "/report/simple/domain_ad_history",
        "/report/simple/domain_dashboard",
        "/report/simple/domain_dashboard/ai-answers",
        "/report/simple/domain_dashboard/ai-concurents",
        "/report/simple/keyword_dashboard",
        "/report/simple/links/backlinks",
        "/report/simple/links/backlinks-anchor",
        "/report/simple/links/backlinks-domains",
        "/report/simple/links/pages",
        "/report/simple/organic/ai-concurents",
        "/report/simple/organic/concurents",
        "/report/simple/organic/keywords",
        "/report/simple/organic/lost_keywords",
        "/report/simple/organic/sitepages",
        "/report/simple/organic/sitepages/withkeys",
        "/report/simple/similarkeys",
        # Coverage round 2026-10 (apidoc.keys.so): pages, links, visibility, Direct, robots, Zen, groups.
        "/report/simple/organic/concurent_pages",
        "/report/simple/organic/keywords/bypage",
        "/report/simple/organic/lost_pages",
        "/report/simple/organic/ai-answers",
        "/report/simple/links/outlinks",
        "/report/simple/links/outlinks-domains",
        "/report/simple/links/backlinks-ip",
        "/report/simple/links/backlinks-ip/subnet",
        "/report/simple/top_domain_visibility",
        "/report/simple/direct/ads",
        "/report/owner/subdomains",
        "/report/ads/rsya",
        "/report/group/list",
        "/robots/dates",
        "/robots/data",
        "/zen/dashboard",
        "/zen/top/channels",
        "/zen/channel/publications",
        "/zen/channel/new/top/publications",
        "/projects",
        "/projects/competitors",
    }
)
ALLOWED_PARAMS = frozenset(
    {
        "ads_id",
        "base",
        "channel",
        "date",
        "domain",
        "forDay",
        "groupingBy",
        "id",
        "includeSubLevels",
        "kid",
        "projectId",
        "url",
        "page_url",
        "excl",
        "full",
        "incl",
        "keyword",
        "limit",
        "month",
        "page",
        "per_page",
        "sort",
        "top",
        "view",
    }
)
# Keys.so API changelog 1.0.25 (2026-10-01): sorting context keywords by these fields returns HTTP 400.
_CONTEXT_KEYWORD_PATHS = frozenset(
    {
        "/report/simple/context/keywords",
        "/report/simple/context/keywords/archive",
        "/report/simple/context/keywords/byads",
        "/report/simple/context/keywords/byads/archive",
    }
)
_UNSORTABLE_CONTEXT_FIELDS = frozenset({"header", "txt", "url"})
# 1.0.26 (2026-10-08): the keyword ads archive sorts only by keyscnt and serp.
_SORT_ONLY = {"/report/simple/context/keyword/ads/archive": frozenset({"keyscnt", "serp"})}
MAX_KEYWORD_CHARS = 512
ALLOWED_VIEWS = frozenset({"organic", "context", "backlinks"})
_DOMAIN = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{1,62}\Z")
_RSYA_PATH = re.compile(r"/report/ads/rsya/domains/([^/]+)\Z")
_PAGE_URL_PATHS = frozenset(
    {"/report/simple/organic/keywords/bypage", "/report/simple/organic/concurent_pages"}
)
# Saved group reports (read-only): /report/group/<section>/<rid>; creation is not exposed.
_GROUP_PATH = re.compile(
    r"/report/group/(?:state|domains|organic/(?:keywords|concurents|sitepages)"
    r"|context/(?:keywords|concurents|ads|ads/links|ads/facts))/[A-Za-z0-9:_-]{1,128}\Z"
)


class JsonRequester(Protocol):
    async def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any: ...


def _validated_domain(value: object, field: str) -> str:
    try:
        normalized = str(value).strip().lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"{field} must contain valid DNS domains") from exc
    if _DOMAIN.fullmatch(normalized) is None:
        raise ValueError(f"{field} must contain valid DNS domains")
    return normalized


def _text(value: object, field: str) -> str:
    # Never stringify lists, numbers or booleans into a provider parameter.
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _validated_positive_int(value: object, field: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        try:
            normalized = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be a positive integer") from exc
    else:
        raise ValueError(f"{field} must be a positive integer")
    if normalized < 1 or normalized > maximum:
        raise ValueError(f"{field} must be between 1 and {maximum}")
    return normalized


class KeysSoAdapter:
    """Strict, read-only Keys.so adapter with a fixed report allowlist."""

    def __init__(
        self,
        base_url: str,
        token: str,
        http: JsonRequester | None = None,
        coalescer: AsyncSingleFlight | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.http = http or JsonHttpClient(timeout=60)
        self.coalescer = coalescer or AsyncSingleFlight()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise ProviderError("Keys.so token is not configured")
        return {
            "Accept": "application/json",
            "X-Keyso-TOKEN": self.token,
            "User-Agent": f"ZAI-ONE-Keysso-MCP/{__version__}",
        }

    @staticmethod
    def validate(path: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        normalized_path = "/" + path.strip().lstrip("/")
        rsya = _RSYA_PATH.fullmatch(normalized_path)
        group = _GROUP_PATH.fullmatch(normalized_path)
        if normalized_path not in ALLOWED_PATHS and rsya is None and group is None:
            raise ValueError("Keys.so report path is not allowed")
        if normalized_path in _PAGE_URL_PATHS and "page_url" not in params:
            # apidoc: these reports require page_url (a plain url is ignored by Keys.so)
            raise ValueError(f"{normalized_path} requires page_url")
        if rsya is not None:
            _validated_domain(rsya.group(1), "RSYA path")

        unknown = sorted(set(params) - ALLOWED_PARAMS)
        if unknown:
            raise ValueError("unsupported Keys.so parameters: " + ", ".join(unknown))
        validated = dict(params)
        for field in (
            "domain",
            "incl",
            "excl",
            "base",
            "view",
            "keyword",
            "month",
            "sort",
            "url",
            "page_url",
            "channel",
            "groupingBy",
        ):
            if field in validated:
                _text(validated[field], field)
        if "domain" in validated:
            validated["domain"] = _validated_domain(validated["domain"], "domain")
        if "incl" in validated:
            domains = [item.strip() for item in validated["incl"].split(",") if item.strip()]
            if not domains or len(domains) > 20:
                raise ValueError("incl must contain between 1 and 20 domains")
            validated["incl"] = ",".join(_validated_domain(item, "incl") for item in domains)
        if validated.get("excl", ""):
            domains = [item.strip() for item in validated["excl"].split(",") if item.strip()]
            if len(domains) > 20:
                raise ValueError("excl must contain at most 20 domains")
            validated["excl"] = ",".join(_validated_domain(item, "excl") for item in domains)
        if "base" in validated:
            base = validated["base"].strip().lower()
            if re.fullmatch(r"[a-z0-9_-]{1,32}", base) is None:
                raise ValueError("base is not allowed")
            validated["base"] = base
        if "view" in validated:
            view = validated["view"].strip().lower()
            if view not in ALLOWED_VIEWS:
                raise ValueError("view is not allowed")
            validated["view"] = view
        bounded_ints = (
            ("page", 100),
            ("per_page", 500),
            ("limit", 100),
            ("top", 100),
            ("ads_id", 2_147_483_647),
            ("kid", 2_147_483_647),
            ("id", 2_147_483_647),
            ("projectId", 2_147_483_647),
        )
        for field, maximum in bounded_ints:
            if field in validated:
                validated[field] = _validated_positive_int(validated[field], field, maximum)
        if "keyword" in validated:
            keyword = " ".join(validated["keyword"].split())
            if not keyword or len(keyword) > MAX_KEYWORD_CHARS:
                raise ValueError(f"keyword must contain 1-{MAX_KEYWORD_CHARS} characters")
            validated["keyword"] = keyword
        if "month" in validated:
            month = validated["month"].strip()
            if re.fullmatch(r"\d{4}-\d{2}", month) is None:
                raise ValueError("month must use YYYY-MM")
            try:
                date.fromisoformat(month + "-01")
            except ValueError as exc:
                raise ValueError("month must use YYYY-MM") from exc
            validated["month"] = month
        for field in ("url", "page_url", "channel", "groupingBy"):
            if field in validated:
                text = validated[field].strip()
                if not 1 <= len(text) <= 2048 or re.search(r"[\x00-\x1f\x7f]", text):
                    raise ValueError(f"{field} must contain 1-2048 printable characters")
                validated[field] = text
        for field in ("date", "forDay"):
            if field in validated:
                day = validated[field]
                if not isinstance(day, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", day.strip()) is None:
                    raise ValueError(f"{field} must use YYYY-MM-DD")
                date.fromisoformat(day.strip())
                validated[field] = day.strip()
        if "includeSubLevels" in validated:
            flag = validated["includeSubLevels"]
            if not (isinstance(flag, (bool, int, str)) and flag in (0, 1, "0", "1")):
                raise ValueError("includeSubLevels must be a boolean")
            validated["includeSubLevels"] = int(flag)
        if "full" in validated:
            full = validated["full"]
            # Exact types only: an unhashable list must not reach a set lookup, a float is not a flag.
            if not (isinstance(full, (bool, int, str)) and full in (0, 1, "0", "1")):
                raise ValueError("full must be a boolean")
            validated["full"] = int(full)
        if "sort" in validated:
            sort = validated["sort"].strip()
            if not re.fullmatch(
                r"[a-zA-Z0-9_]{1,64}\|(asc|desc)(,[a-zA-Z0-9_]{1,64}\|(asc|desc)){0,2}", sort
            ):
                raise ValueError("sort must use field|asc or field|desc (up to three, comma-separated)")
            fields = {item.split("|", 1)[0] for item in sort.split(",")}
            if normalized_path in _CONTEXT_KEYWORD_PATHS and fields & _UNSORTABLE_CONTEXT_FIELDS:
                raise ValueError("Keys.so does not sort context keywords by header, txt or url")
            allowed_sort = _SORT_ONLY.get(normalized_path)
            if allowed_sort is not None and not fields <= allowed_sort:
                raise ValueError("this report sorts only by: " + ", ".join(sorted(allowed_sort)))
            validated["sort"] = sort
        return normalized_path, validated

    async def ai_tracker(self, report: str, tracker_id: int | None = None, **arguments: Any) -> Any:
        path, params = ai_tracker_request(report, tracker_id, **arguments)
        return await self._get(path, params)

    async def limits(self) -> Any:
        """Remaining plan limits per tool: GET /limits/all (https://apidoc.keys.so/)."""
        return await self._get(LIMITS_PATH, {})

    async def query(self, path: str, params: dict[str, Any]) -> Any:
        normalized_path, validated = self.validate(path, params)
        return await self._get(normalized_path, validated)

    async def job(
        self, method: str, path: str, params: dict[str, Any], payload: dict[str, Any] | None
    ) -> Any:
        """Keyword jobs, clustering and monitoring (paths built and validated by zai_keysso.jobs)."""
        if method == "GET":
            return await self._get(path, params)
        return await self.http.request_json(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            payload=payload or {},
            params=params or None,
        )

    async def _get(self, normalized_path: str, validated: dict[str, Any]) -> Any:
        key = request_hash({"provider": "keys_so", "path": normalized_path, "params": validated})
        return await self.coalescer.run(
            key,
            lambda: self.http.request_json(
                "GET",
                f"{self.base_url}{normalized_path}",
                headers=self._headers(),
                params=validated,
            ),
        )
