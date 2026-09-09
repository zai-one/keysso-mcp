from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

from zai_keysso import __version__
from zai_keysso.adapter import KeysSoAdapter
from zai_keysso.catalog import report_catalog
from zai_keysso.coalescing import AsyncSingleFlight
from zai_keysso.config import ServiceConfig
from zai_keysso.onboarding import check_config, load_config
from zai_keysso.policy import PolicyStore
from zai_keysso.reports import collect_report, comparison_request, domain_request, validate_bounds
from zai_keysso.sanitizer import redact_literal, sanitize_provider_response
from zai_keysso.transport import (
    JsonHttpClient,
    ProviderAdmissionDenied,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeoutError,
    RetryPolicy,
    request_hash,
)

TOOL_NAME = "keys_so_query"
SCOPE = "keys_so:read"
OPERATION_TIMEOUT_SECONDS = 75.0
T = TypeVar("T")


class RequestOwnedFlight(AsyncSingleFlight):
    """Keep upstream cancellation within the one owning MCP call.

    Each service call creates its own adapter, so there are no other callers
    to preserve by shielding a shared task.
    """

    async def run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        return await factory()


def _timestamp(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def authorize(
    config: ServiceConfig, transport: str, arguments: dict[str, Any], tool_name: str = TOOL_NAME
) -> dict[str, Any]:
    if transport == "stdio":
        return {"actor": config.principal_id, "request_id": uuid4().hex}
    access = get_access_token()
    if access is None or SCOPE not in access.scopes:
        raise PermissionError("Keys.so read scope required")
    claims = access.claims
    actor = claims.get("sub")
    now = time.time()
    if (
        not isinstance(actor, str)
        or not actor
        or len(actor) > 256
        or claims.get("account_id") != config.account_id
        or not _timestamp(claims.get("exp"))
        or claims["exp"] <= now
    ):
        raise PermissionError("invalid account-bound identity")
    result: dict[str, Any] = {"actor": actor, "request_id": uuid4().hex}
    if config.auth_mode == "delegated":
        issued = claims.get("iat")
        nonce = claims.get("jti")
        request_id = claims.get("request_id")
        if (
            not _timestamp(issued)
            or issued > now + 5
            or claims["exp"] - issued > config.delegated_ttl
            or claims["exp"] <= issued
            or claims.get("tool") != tool_name
            or claims.get("request_hash") != request_hash(arguments)
            or not isinstance(nonce, str)
            or not 1 <= len(nonce) <= 128
            or not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 128
        ):
            raise PermissionError("invalid request-bound delegation")
        result.update(request_id=request_id, nonce=nonce, expires=claims["exp"])
    return result


class AdmittedHttpClient(JsonHttpClient):
    def __init__(self, store: PolicyStore, execution_id: str, actor: str, delegated: bool):
        super().__init__(timeout=60, retry=RetryPolicy(attempts=1 if delegated else 3))
        self.store, self.execution_id, self.actor = store, execution_id, actor
        self.admissions = 0

    async def _admit_attempt(self, attempt: int) -> None:
        # Each report page restarts the HTTP retry index. Audit every HTTP attempt
        # with a unique ordinal across the entire admitted MCP execution.
        self.admissions += 1
        self.store.admit(self.execution_id, self.actor, self.admissions)


def _safe_error(exc: Exception) -> ToolError:
    # No provider body, secret or exception message crosses this boundary.
    envelope: dict[str, Any] = {"provider": "keys_so", "code": "operation_failed", "retryable": False}
    if isinstance(exc, PermissionError):
        envelope["code"] = "provider_disabled"
    elif isinstance(exc, ValueError):
        envelope["code"] = "validation_failed"
    elif isinstance(exc, ProviderError):
        names = {
            "ProviderAuthenticationError": "provider_authentication_failed",
            "ProviderNotFoundError": "provider_resource_not_found",
            "ProviderTimeoutError": "provider_timeout",
            "ProviderTransportError": "provider_transport_failed",
            "ProviderTransientHttpError": "provider_temporarily_unavailable",
            "ProviderResponseError": "provider_response_invalid",
            "ProviderRequestError": "provider_request_invalid",
            "ProviderHttpError": "provider_http_error",
            "ProviderRequestTooLarge": "provider_payload_too_large",
            "ProviderResponseTooLarge": "provider_payload_too_large",
        }
        envelope["code"] = names.get(type(exc).__name__, "provider_error")
        envelope["retryable"] = envelope["code"] in {
            "provider_timeout",
            "provider_transport_failed",
            "provider_temporarily_unavailable",
        }
        if isinstance(exc, ProviderRateLimited):
            envelope.update(code="provider_rate_limited", retryable=True)
            if isinstance(exc, ProviderAdmissionDenied):
                envelope["origin"] = "admission"
            if exc.retry_after_seconds is not None:
                envelope["retry_after_seconds"] = exc.retry_after_seconds
    return ToolError(json.dumps(envelope, sort_keys=True, separators=(",", ":")))


def create_server(
    config: ServiceConfig,
    *,
    transport: str = "http",
    http_factory: Callable[[PolicyStore, str, str, bool], Any] | None = None,
) -> FastMCP:
    if transport not in {"stdio", "http"}:
        raise ValueError("unsupported transport")
    if transport == "stdio" and config.auth_mode != "operator":
        raise ValueError("delegated mode requires authenticated HTTP")
    auth = None
    if transport == "http":
        if not config.public_key:
            raise ValueError("authenticated HTTP requires an RSA public key")
        auth = JWTVerifier(
            public_key=config.public_key,
            algorithm="RS256",
            issuer=config.issuer,
            audience=config.audience,
            required_scopes=[SCOPE],
        )
    store = PolicyStore(
        config.state_path,
        config.account_id,
        config.rate_limit,
        config.principal_rate_limit,
        config.max_concurrency,
    )
    server = FastMCP("Keysso MCP", version=__version__, auth=auth, mask_error_details=True)

    @server.resource("keysso://reports", mime_type="application/json")
    def reports() -> str:
        """Allowed Keys.so reports, parameter limits and a query example; no API calls."""
        return json.dumps(report_catalog(), ensure_ascii=False)

    async def execute(
        tool_name: str,
        arguments: dict[str, Any],
        validate: Callable[[], Any],
        operation: Callable[[KeysSoAdapter], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        execution_id = uuid4().hex
        begun = False
        try:
            identity = authorize(config, transport, arguments, tool_name)
            validate()
            store.begin(
                execution_id,
                identity["request_id"],
                identity["actor"],
                request_hash(arguments),
                identity.get("nonce"),
                identity.get("expires"),
            )
            begun = True
            factory = http_factory or AdmittedHttpClient
            http = factory(store, execution_id, identity["actor"], config.auth_mode == "delegated")
            adapter = KeysSoAdapter(
                config.base_url, config.provider_token, http=http, coalescer=RequestOwnedFlight()
            )
            # A hard total bound keeps in-flight work inside the 90-second lease,
            # including a peer that sends bytes often enough to reset HTTP read timeouts.
            async with asyncio.timeout(OPERATION_TIMEOUT_SECONDS):
                payload = await operation(adapter)
            # Strip literal configured secrets too, including under innocuous response keys.
            safe_payload = redact_literal(sanitize_provider_response(payload), config.provider_token)
            store.finish(execution_id, "success")
            return safe_payload
        except asyncio.CancelledError:
            # The unshielded upstream has unwound before its lease is released.
            if begun:
                store.finish(execution_id, "cancelled")
            raise
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                exc = ProviderTimeoutError("Keysso operation deadline exceeded")
            if isinstance(exc, ProviderRateLimited) and not isinstance(exc, ProviderAdmissionDenied):
                store.cooldown(exc.retry_after_seconds or 60)
            if begun:
                store.finish(execution_id, "error")
            raise _safe_error(exc) from None

    @server.tool
    async def keys_so_query(path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Run one read-only Keys.so report from the fixed path and parameter allowlist."""

        async def query(adapter: KeysSoAdapter) -> dict[str, Any]:
            return {"payload": await adapter.query(path, params)}

        return await execute(
            TOOL_NAME,
            {"path": path, "params": params},
            lambda: KeysSoAdapter.validate(path, params),
            query,
        )

    @server.tool
    async def keysso_domain_report(
        report: Literal["keywords", "competitors", "pages", "backlinks"],
        domain: str,
        base: str = "msk",
        sort: str | None = None,
        start_page: int = 1,
        max_pages: int = 1,
        page_size: int = 100,
        output: Literal["json", "csv"] = "json",
    ) -> dict[str, Any]:
        """Read up to five pages of a domain report. Return provenance, completeness and JSON or CSV.

        Each page spends provider request quota. Backlinks do not use the regional base.
        A partial result includes a stop reason; never describe it as a complete audit.
        """
        arguments = {
            "report": report,
            "domain": domain,
            "base": base,
            "sort": sort,
            "start_page": start_page,
            "max_pages": max_pages,
            "page_size": page_size,
            "output": output,
        }

        def validate():
            validate_bounds(start_page, max_pages, page_size, output)
            domain_request(report, domain, base, sort)

        async def query(adapter: KeysSoAdapter) -> dict[str, Any]:
            path, params = domain_request(report, domain, base, sort)
            return await collect_report(
                adapter,
                path,
                params,
                start_page=start_page,
                max_pages=max_pages,
                page_size=page_size,
                output=output,
                secret=config.provider_token,
            )

        return await execute("keysso_domain_report", arguments, validate, query)

    @server.tool
    async def keysso_compare_domains(
        include: list[str],
        exclude: list[str],
        base: str = "msk",
        view: Literal["organic", "context", "backlinks"] = "organic",
        start_page: int = 1,
        max_pages: int = 1,
        page_size: int = 100,
        output: Literal["json", "csv"] = "json",
    ) -> dict[str, Any]:
        """Compare included domains and exclude others using Keys.so's comparison report.

        Use include=[competitor] and exclude=[your_site] to research a keyword gap.
        Up to five pages; counts describe provider data, not an independently crawled web.
        """
        arguments = {
            "include": include,
            "exclude": exclude,
            "base": base,
            "view": view,
            "start_page": start_page,
            "max_pages": max_pages,
            "page_size": page_size,
            "output": output,
        }

        def validate():
            validate_bounds(start_page, max_pages, page_size, output)
            comparison_request(include, exclude, base, view)

        async def query(adapter: KeysSoAdapter) -> dict[str, Any]:
            path, params = comparison_request(include, exclude, base, view)
            return await collect_report(
                adapter,
                path,
                params,
                start_page=start_page,
                max_pages=max_pages,
                page_size=page_size,
                output=output,
                secret=config.provider_token,
            )

        return await execute("keysso_compare_domains", arguments, validate, query)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone Keys.so MCP")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--config", help="Operator JSON settings; paths relative to this file")
    parser.add_argument(
        "--check-config", action="store_true", help="Check local settings without provider calls"
    )
    args = parser.parse_args()
    try:
        load_config(args.config)
        config = ServiceConfig.from_env()
        if args.check_config:
            result = check_config(config, args.transport)
            print(json.dumps(result, sort_keys=True))
            parser.exit(0 if result["ready"] else 2)
        server = create_server(config, transport=args.transport)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"configuration error: {type(exc).__name__}; check credential and policy files\n")
    if args.transport == "http":
        server.run(
            transport="http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
            show_banner=False,
            log_level="warning",
        )
    else:
        server.run(transport="stdio", show_banner=False, log_level="warning")
