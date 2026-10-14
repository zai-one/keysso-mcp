from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

from zai_keysso import __version__
from zai_keysso.adapter import KeysSoAdapter
from zai_keysso.agent_layer import apply as apply_agent_layer
from zai_keysso.agent_layer import router_instructions
from zai_keysso.agent_profile import PROFILE
from zai_keysso.ai_tracker import ai_tracker_request
from zai_keysso.api_calls import needs_approval, validate_call
from zai_keysso.approvals import ApprovalStore
from zai_keysso.catalog import report_catalog
from zai_keysso.coalescing import AsyncSingleFlight
from zai_keysso.config import ServiceConfig
from zai_keysso.jobs import (
    CONFIRM_HINT,
    MONITORING_WRITES,
    clustering_request,
    keyword_job_request,
    monitoring_request,
    monitoring_write_request,
)
from zai_keysso.onboarding import check_config, load_config
from zai_keysso.policy import PolicyStore
from zai_keysso.reports import (
    collect_report,
    comparison_request,
    domain_request,
    validate_bounds,
    validate_fields,
)
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
from zai_keysso.update_check import CACHE_FILE, cached_hint, check_update, refresh_in_background

TOOL_NAME = "keys_so_query"
# MCP tool annotations: every Keys.so tool only reads provider data (and spends request quota).
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
# The update check reads GitHub, not Keys.so. Not idempotent: force_refresh may fetch again and
# rewrite the local version cache, so repeated calls can change what later calls return.
UPDATE_CHECK = {**READ_ONLY, "idempotentHint": False}
# Keyword jobs, clustering and monitoring starts create provider-side jobs and spend plan limits.
JOB = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
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


def _approval_error(code: str, message: str) -> ToolError:
    envelope = {"provider": "keys_so", "code": code, "message": message, "retryable": False}
    return ToolError(json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _consume(approvals: Any, approval_id: str, tool_name: str, request: dict[str, Any]) -> None:
    try:
        approvals.consume(approval_id, tool_name, request)
    except PermissionError as exc:
        raise _approval_error("approval_invalid", str(exc)) from None


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
    approvals = ApprovalStore(config.state_path.with_name("keysso-approvals.json"))
    store = PolicyStore(
        config.state_path,
        config.account_id,
        config.rate_limit,
        config.principal_rate_limit,
        config.max_concurrency,
    )
    update_cache = update_cache_path(config)
    server = FastMCP(
        "Keysso MCP",
        version=__version__,
        auth=auth,
        mask_error_details=True,
        instructions=router_instructions(PROFILE, cached_hint(update_cache)),
    )

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
            try:
                validate()
            except TypeError as exc:  # a wrongly typed argument is a validation error, not a failure
                raise ValueError("invalid parameter type") from exc
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

    @server.tool(annotations=READ_ONLY)
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

    @server.tool(annotations=READ_ONLY)
    async def keysso_domain_report(
        report: Literal["keywords", "competitors", "pages", "backlinks"],
        domain: str,
        base: str = "msk",
        sort: str | None = None,
        start_page: int = 1,
        max_pages: int = 1,
        page_size: int = 100,
        output: Literal["json", "csv"] = "json",
        fields: list[str] | None = None,
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
        if fields is not None:
            # Hashed for delegation only when provided, so the documented default set still matches.
            arguments["fields"] = fields

        def validate():
            validate_bounds(start_page, max_pages, page_size, output)
            validate_fields(fields)
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
                fields=fields,
            )

        return await execute("keysso_domain_report", arguments, validate, query)

    @server.tool(annotations=READ_ONLY)
    async def keysso_compare_domains(
        include: list[str],
        exclude: list[str],
        base: str = "msk",
        view: Literal["organic", "context", "backlinks"] = "organic",
        start_page: int = 1,
        max_pages: int = 1,
        page_size: int = 100,
        output: Literal["json", "csv"] = "json",
        fields: list[str] | None = None,
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
        if fields is not None:
            # Hashed for delegation only when provided, so the documented default set still matches.
            arguments["fields"] = fields

        def validate():
            validate_bounds(start_page, max_pages, page_size, output)
            validate_fields(fields)
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
                fields=fields,
            )

        return await execute("keysso_compare_domains", arguments, validate, query)

    @server.tool(annotations=READ_ONLY)
    async def keysso_ai_tracker(
        report: Literal[
            "projects",
            "entity",
            "dates",
            "report",
            "mentions",
            "citation",
            "reference",
            "sources",
            "competitors",
            "prompt",
        ],
        tracker_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        systems: list[int] | None = None,
        groups: list[str] | None = None,
        search: str | None = None,
        view: Literal["url", "domain"] | None = None,
        last: bool | None = None,
        prompt_id: int | None = None,
        date: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> dict[str, Any]:
        """Read Keys.so AI tracker (GEO) data for your trackers; never creates, starts or deletes anything.

        report=projects lists trackers (no tracker_id). With tracker_id: entity (brand, systems, groups),
        dates, report (prompt mentions for date_from..date_to), mentions, citation (site cited in sources),
        reference (brand vs competitors visibility), sources (view=url|domain), competitors,
        prompt (answers for prompt_id on date). systems: 1 GigaChat, 3 DeepSeek, 5 Perplexity,
        6 ChatGPT, 8 Alice AI in Search, 9 Google AI Mode, 10 Gemini, 11 Claude, 12 Alice AI chat.
        """
        optional = {
            "date_from": date_from,
            "date_to": date_to,
            "systems": systems,
            "groups": groups,
            "search": search,
            "view": view,
            "last": last,
            "prompt_id": prompt_id,
            "date": date,
            "page": page,
            "per_page": per_page,
        }
        arguments = {"report": report, "tracker_id": tracker_id, **optional}

        async def query(adapter: KeysSoAdapter) -> dict[str, Any]:
            return {"payload": await adapter.ai_tracker(report, tracker_id, **optional)}

        return await execute(
            "keysso_ai_tracker", arguments, lambda: ai_tracker_request(report, tracker_id, **optional), query
        )

    async def execute_local(
        tool_name: str, arguments: dict[str, Any], operation: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Authorize and audit a tool that never calls Keys.so: no provider admission or quota."""
        execution_id = uuid4().hex
        begun = False
        try:
            identity = authorize(config, transport, arguments, tool_name)
            store.begin(
                execution_id,
                identity["request_id"],
                identity["actor"],
                request_hash(arguments),
                identity.get("nonce"),
                identity.get("expires"),
            )
            begun = True
            payload = await operation()
            store.finish(execution_id, "success")
            return payload
        except asyncio.CancelledError:
            if begun:
                store.finish(execution_id, "cancelled")
            raise
        except Exception as exc:
            if begun:
                store.finish(execution_id, "error")
            raise _safe_error(exc) from None

    async def run_job(
        tool_name: str,
        arguments: dict[str, Any],
        build: Callable[[], tuple[str, str, dict[str, Any], dict[str, Any] | None]],
        spends: bool,
        confirm: bool,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        if spends and confirm is True:
            method, path, params, payload = build()
            request = {"method": method, "path": path, "params": params, "payload": payload}
            if not approval_id:

                async def prepare() -> dict[str, Any]:
                    return _approval_needed(tool_name, request, f"{method} {path}")

                return await execute_local(tool_name, arguments, prepare)
            _consume(approvals, approval_id, tool_name, request)
        if spends and confirm is not True:

            async def preview() -> dict[str, Any]:
                method, path, _, payload = build()
                size = len((payload or {}).get("list") or (payload or {}).get("keywords") or [])
                return {
                    "needs_confirmation": True,
                    "method": method,
                    "path": path,
                    "phrases": size,
                    "hint": CONFIRM_HINT,
                }

            return await execute_local(tool_name, arguments, preview)

        async def call(adapter: KeysSoAdapter) -> dict[str, Any]:
            method, path, params, payload = build()
            return {"payload": await adapter.job(method, path, params, payload)}

        return await execute(tool_name, arguments, build, call)

    @server.tool(annotations=JOB)
    async def keysso_keyword_job(
        kind: Literal["keywords_by_list", "extended_keywords", "concurents_by_keywords"],
        action: Literal["start", "status", "result"],
        phrases: list[str] | None = None,
        base: str = "msk",
        uid: str | None = None,
        top: int | None = None,
        view: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
        sort: str | None = None,
        similarity: int | None = None,
        confirm: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a Keys.so keyword tool job: start -> status -> result (paged).

        keywords_by_list: frequencies/metrics for your phrase list (mass check); extended_keywords:
        expand phrases into a semantic core; concurents_by_keywords: competitor share for phrases
        (top 10|50; result view=organic|context). extended_keywords start takes similarity 5-100.
        start spends limits and needs confirm=true.
        """
        arguments = {
            "kind": kind,
            "action": action,
            "phrases": phrases,
            "base": base,
            "uid": uid,
            "top": top,
            "view": view,
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "similarity": similarity,
            "confirm": confirm,
        }

        def build() -> Any:
            return keyword_job_request(
                kind,
                action,
                phrases=phrases,
                base=base,
                uid=uid,
                top=top,
                view=view,
                page=page,
                per_page=per_page,
                sort=sort,
                similarity=similarity,
            )

        return await run_job("keysso_keyword_job", arguments, build, action == "start", confirm, approval_id)

    @server.tool(annotations=JOB)
    async def keysso_clustering(
        action: Literal["list", "create", "build", "status", "folders", "keywords"],
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
        confirm: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Cluster phrases by SERP overlap in Keys.so: create -> build -> status -> folders -> keywords.

        create(phrases, base) returns uid; build(uid, top_number 10|20|50, strength %, min_frequency)
        starts SERP+frequency collection. create/build spend limits and need confirm=true.
        """
        arguments = {
            "action": action,
            "phrases": phrases,
            "base": base,
            "uid": uid,
            "folder_id": folder_id,
            "top_number": top_number,
            "strength": strength,
            "min_frequency": min_frequency,
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "confirm": confirm,
        }

        def build() -> Any:
            return clustering_request(
                action,
                phrases=phrases,
                base=base,
                uid=uid,
                folder_id=folder_id,
                top_number=top_number,
                strength=strength,
                min_frequency=min_frequency,
                page=page,
                per_page=per_page,
                sort=sort,
            )

        return await run_job(
            "keysso_clustering", arguments, build, action in {"create", "build"}, confirm, approval_id
        )

    @server.tool(annotations=JOB)
    async def keysso_monitoring(
        action: Literal[
            "projects", "entity", "dates", "report", "compare", "chart", "limits", "create", "start"
        ],
        project_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        region_id: int | None = None,
        engine: int | None = None,
        folder_ids: list[int] | None = None,
        search: str | None = None,
        tracking_item: str | None = None,
        cluster_uid: str | None = None,
        phrases: list[str] | None = None,
        name: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
        sort: str | None = None,
        confirm: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Keys.so position monitoring: read projects/report/compare/chart/dates/limits; create/start.

        create(tracking_item, cluster_uid or phrases, region_id, engine 0 Yandex|1 Google) makes a project
        from clusters; start(project_id) is a paid position refresh. create/start need confirm=true.
        """
        arguments = {
            "action": action,
            "project_id": project_id,
            "date_from": date_from,
            "date_to": date_to,
            "region_id": region_id,
            "engine": engine,
            "folder_ids": folder_ids,
            "search": search,
            "tracking_item": tracking_item,
            "cluster_uid": cluster_uid,
            "phrases": phrases,
            "name": name,
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "confirm": confirm,
        }

        def build() -> Any:
            if action in MONITORING_WRITES:
                return monitoring_write_request(
                    action,
                    project_id=project_id,
                    tracking_item=tracking_item,
                    cluster_uid=cluster_uid,
                    phrases=phrases,
                    region_id=region_id or 213,
                    engine=engine or 0,
                    name=name,
                    folder_ids=folder_ids,
                )
            return monitoring_request(
                action,
                project_id=project_id,
                date_from=date_from,
                date_to=date_to,
                region_id=region_id,
                engine=engine,
                folder_ids=folder_ids,
                search=search,
                page=page,
                per_page=per_page,
                sort=sort,
            )

        return await run_job(
            "keysso_monitoring", arguments, build, action in MONITORING_WRITES, confirm, approval_id
        )

    def _approval_needed(tool_name: str, request: dict[str, Any], summary: str) -> dict[str, Any]:
        ticket = approvals.prepare(tool_name, request, summary)
        return {
            "needs_operator_approval": True,
            **ticket,
            "summary": summary,
            "operator_command": f"keysso-approval --approval-id {ticket['approval_id']} "
            f"--digest {ticket['digest']} --accept",
            "hint": "Show the request to the user; after the operator accepts, repeat the same call "
            "with approval_id. The agent never runs the operator command.",
        }

    @server.tool(annotations=JOB)
    async def keysso_api(
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | list[Any] | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Call one documented Keys.so endpoint (tools/*, wordstat/*, serp/*, clustering, monitoring).

        GET runs at once. POST/PATCH/DELETE spend limits or change data: the first call returns
        approval_id + digest for the operator; repeat with approval_id after acceptance.
        """
        arguments = {"method": method, "path": path, "params": params, "body": body}
        try:
            verb, clean_path, clean_params, payload = validate_call(method, path, params, body)
        except ValueError as exc:
            raise _approval_error("validation_failed", str(exc)) from None
        request = {"method": verb, "path": clean_path, "params": clean_params, "payload": payload}
        if needs_approval(verb):
            if not approval_id:

                async def prepare() -> dict[str, Any]:
                    return _approval_needed("keysso_api", request, f"{verb} {clean_path}")

                return await execute_local("keysso_api", arguments, prepare)
            _consume(approvals, approval_id, "keysso_api", request)

        async def call(adapter: KeysSoAdapter) -> dict[str, Any]:
            return {"payload": await adapter.job(verb, clean_path, clean_params, payload)}

        return await execute("keysso_api", arguments, lambda: None, call)

    @server.tool(annotations=READ_ONLY)
    async def keysso_limits() -> dict[str, Any]:
        """Read remaining Keys.so plan limits per tool (GET /limits/all)."""

        async def query(adapter: KeysSoAdapter) -> dict[str, Any]:
            return {"payload": await adapter.limits()}

        return await execute("keysso_limits", {}, lambda: None, query)

    @server.tool(annotations=UPDATE_CHECK)
    async def keysso_check_update(force_refresh: bool = False) -> dict[str, Any]:
        """Compare the installed version with the latest GitHub release and suggest an update command.

        Read-only; never installs anything and spends no Keys.so quota. Uses a 24h cache; a forced
        refresh runs at most once a minute. Set KEYSSO_DISABLE_UPDATE_CHECK=1 to opt out.
        """

        async def operation() -> dict[str, Any]:
            return await asyncio.to_thread(check_update, update_cache, force=force_refresh)

        return await execute_local("keysso_check_update", {"force_refresh": force_refresh}, operation)

    apply_agent_layer(server, PROFILE)
    return server


def update_cache_path(config: ServiceConfig) -> Path:
    return config.state_path.parent / CACHE_FILE


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
        # Non-blocking: refresh a stale update cache for the next start; failures are silent.
        refresh_in_background(update_cache_path(config))
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
