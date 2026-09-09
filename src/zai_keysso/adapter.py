from __future__ import annotations

import re
from typing import Any, Protocol

from zai_keysso import __version__
from zai_keysso.coalescing import AsyncSingleFlight
from zai_keysso.transport import JsonHttpClient, ProviderError, request_hash

ALLOWED_PATHS = frozenset(
    {
        "/limits/all",
        "/report/compare",
        "/report/simple/context/ads",
        "/report/simple/context/ads/facts",
        "/report/simple/context/ads/links",
        "/report/simple/context/concurents",
        "/report/simple/context/keywords",
        "/report/simple/context/keywords/byads",
        "/report/simple/direct/domain",
        "/report/simple/domain_ad_history",
        "/report/simple/domain_dashboard",
        "/report/simple/domain_dashboard/ai-answers",
        "/report/simple/domain_dashboard/ai-concurents",
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
    }
)
ALLOWED_PARAMS = frozenset(
    {"ads_id", "base", "domain", "excl", "incl", "limit", "page", "per_page", "sort", "top", "view"}
)
ALLOWED_VIEWS = frozenset({"organic", "context", "backlinks"})
_DOMAIN = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{1,62}\Z")
_RSYA_PATH = re.compile(r"/report/ads/rsya/domains/([^/]+)\Z")


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
        if normalized_path not in ALLOWED_PATHS and rsya is None:
            raise ValueError("Keys.so report path is not allowed")
        if rsya is not None:
            _validated_domain(rsya.group(1), "RSYA path")

        unknown = sorted(set(params) - ALLOWED_PARAMS)
        if unknown:
            raise ValueError("unsupported Keys.so parameters: " + ", ".join(unknown))
        validated = dict(params)
        if "domain" in validated:
            validated["domain"] = _validated_domain(validated["domain"], "domain")
        if "incl" in validated:
            domains = [item.strip() for item in str(validated["incl"]).split(",") if item.strip()]
            if not domains or len(domains) > 20:
                raise ValueError("incl must contain between 1 and 20 domains")
            validated["incl"] = ",".join(_validated_domain(item, "incl") for item in domains)
        if str(validated.get("excl", "")):
            domains = [item.strip() for item in str(validated["excl"]).split(",") if item.strip()]
            if len(domains) > 20:
                raise ValueError("excl must contain at most 20 domains")
            validated["excl"] = ",".join(_validated_domain(item, "excl") for item in domains)
        if "base" in validated:
            base = str(validated["base"]).strip().lower()
            if re.fullmatch(r"[a-z0-9_-]{1,32}", base) is None:
                raise ValueError("base is not allowed")
            validated["base"] = base
        if "view" in validated:
            view = str(validated["view"]).strip().lower()
            if view not in ALLOWED_VIEWS:
                raise ValueError("view is not allowed")
            validated["view"] = view
        bounded_ints = (
            ("page", 100),
            ("per_page", 500),
            ("limit", 100),
            ("top", 100),
            ("ads_id", 2_147_483_647),
        )
        for field, maximum in bounded_ints:
            if field in validated:
                validated[field] = _validated_positive_int(validated[field], field, maximum)
        if "sort" in validated:
            sort = str(validated["sort"]).strip()
            if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}\|(asc|desc)", sort):
                raise ValueError("sort must use field|asc or field|desc")
            validated["sort"] = sort
        return normalized_path, validated

    async def query(self, path: str, params: dict[str, Any]) -> Any:
        normalized_path, validated = self.validate(path, params)
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
