"""Regression tests for the approval gate: bindings, reservation order, unknown outcomes, bounds."""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from test_jobs import Recorder, approve, key_pair, server  # noqa: F401 - key_pair is a fixture
from test_server import bearer, configuration, connection

from zai_keysso import approvals as approvals_module
from zai_keysso.api_calls import needs_approval, validate_call
from zai_keysso.approvals import ApprovalQuotaExceeded, ApprovalStore
from zai_keysso.jobs import monitoring_request, monitoring_write_request
from zai_keysso.policy import PolicyStore
from zai_keysso.server import create_server
from zai_keysso.transport import ProviderHttpError, ProviderTimeoutError

DELETE = {"method": "DELETE", "path": "/monitoring/7"}


class Failing(Recorder):
    def __init__(self, failure):
        super().__init__({})
        self.failure, self.single = failure, []

    def factory(self, store, execution_id, actor, single_attempt):
        self.single.append(single_attempt)
        http = super().factory(store, execution_id, actor, single_attempt)
        owner, original = self, http.request_json

        async def request_json(method, url, **kwargs):
            await original(method, url, **kwargs)
            if owner.failure is not None:
                raise owner.failure
            return {}

        http.request_json = request_json
        return http


def error(exc: Exception) -> dict:
    return json.loads(str(exc))


async def test_approval_is_bound_to_account_and_provider(tmp_path, key_pair, monkeypatch):  # noqa: F811
    """Two ledgers in one state directory share the approval file but not each other's approvals."""
    source = Recorder({})
    monkeypatch.setenv("KEYSSO_TOOLSETS", "all")
    other = create_server(
        configuration(tmp_path, key_pair, auth_mode="operator", account_id="b", provider_token="other-token"),
        transport="stdio",
        http_factory=source.factory,
    )
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as a, Client(other) as b:
        ticket = (await a.call_tool("keysso_api", DELETE)).data
        approve(tmp_path, ticket)
        with pytest.raises(ToolError, match="exact request"):
            await b.call_tool("keysso_api", {**DELETE, "approval_id": ticket["approval_id"]})
        assert source.calls == []
        await a.call_tool("keysso_api", {**DELETE, "approval_id": ticket["approval_id"]})
    assert [call[0] for call in source.calls] == ["DELETE"]
    record = ApprovalStore(tmp_path / "keysso-approvals.json")
    assert record.pending() == []


def test_approval_is_bound_to_principal(tmp_path):
    store = ApprovalStore(tmp_path / "keysso-approvals.json")
    ticket = store.prepare("keysso_api", DELETE, "DELETE", "alice", "bind")
    store.accept(ticket["approval_id"], ticket["digest"])
    with pytest.raises(PermissionError):
        store.consume(ticket["approval_id"], "keysso_api", DELETE, "mallory", "bind")
    with pytest.raises(PermissionError):
        store.consume(ticket["approval_id"], "keysso_api", DELETE, "alice", "other-binding")
    store.consume(ticket["approval_id"], "keysso_api", DELETE, "alice", "bind")


async def test_wrong_account_token_does_not_burn_approval(tmp_path, key_pair, monkeypatch):  # noqa: F811
    monkeypatch.setenv("KEYSSO_TOOLSETS", "all")
    source = Recorder({})
    config = configuration(tmp_path, key_pair, auth_mode="operator")
    app_server = create_server(config, http_factory=source.factory)
    async with connection(app_server, bearer(key_pair)) as client:
        ticket = (await client.call_tool("keysso_api", DELETE)).data
    approve(tmp_path, ticket)
    applied = {**DELETE, "approval_id": ticket["approval_id"]}
    async with connection(app_server, bearer(key_pair, account_id="other")) as client:
        with pytest.raises(ToolError, match="provider_disabled"):
            await client.call_tool("keysso_api", applied)
    async with connection(app_server, bearer(key_pair)) as client:
        await client.call_tool("keysso_api", applied)
    assert [call[0] for call in source.calls] == ["DELETE"]


async def test_admission_denial_preserves_the_approval(tmp_path, key_pair, monkeypatch):  # noqa: F811
    source = Recorder({})
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        ticket = (await client.call_tool("keysso_api", DELETE)).data
        approve(tmp_path, ticket)
        policy = PolicyStore(tmp_path / "state.sqlite", "default", 10, 10)
        policy.cooldown(60)
        applied = {**DELETE, "approval_id": ticket["approval_id"]}
        with pytest.raises(ToolError, match="provider_rate_limited"):
            await client.call_tool("keysso_api", applied)
        with sqlite3.connect(tmp_path / "state.sqlite") as db:
            db.execute("DELETE FROM cooldowns")
        await client.call_tool("keysso_api", applied)
    assert [call[0] for call in source.calls] == ["DELETE"]


async def test_ambiguous_write_failure_is_an_unknown_outcome(tmp_path, key_pair, monkeypatch):  # noqa: F811
    source = Failing(ProviderTimeoutError("provider request timed out"))
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        ticket = (await client.call_tool("keysso_api", DELETE)).data
        approve(tmp_path, ticket)
        applied = {**DELETE, "approval_id": ticket["approval_id"]}
        with pytest.raises(ToolError) as caught:
            await client.call_tool("keysso_api", applied)
        envelope = error(caught.value)
        assert envelope["code"] == "provider_outcome_unknown" and envelope["retryable"] is False
        with pytest.raises(ToolError, match="not accepted"):  # spent, not silently re-armed
            await client.call_tool("keysso_api", applied)
        again = (await client.call_tool("keysso_api", DELETE)).data
    assert again["previous_outcome_unknown"] is True
    listed = ApprovalStore(tmp_path / "keysso-approvals.json").pending()
    assert listed[0]["previous_outcome_unknown"] is True
    assert source.single == [True] and len(source.calls) == 1
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        outcomes = [row[0] for row in db.execute("SELECT outcome FROM calls")]
    assert "unknown" in outcomes


async def test_definite_provider_rejection_spends_without_unknown(tmp_path, key_pair, monkeypatch):  # noqa: F811
    source = Failing(ProviderHttpError(400))
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        ticket = (await client.call_tool("keysso_api", DELETE)).data
        approve(tmp_path, ticket)
        with pytest.raises(ToolError, match="provider_http_error"):
            await client.call_tool("keysso_api", {**DELETE, "approval_id": ticket["approval_id"]})
        again = (await client.call_tool("keysso_api", DELETE)).data
    assert "previous_outcome_unknown" not in again


async def test_serp_csv_export_needs_approval(tmp_path, key_pair, monkeypatch):  # noqa: F811
    """apidoc: GET /serp/<id>/csv queues an export job, so it is not a free read."""
    assert needs_approval("GET", "/serp/12/csv") and not needs_approval("GET", "/serp/12/csv/export-status")
    source = Failing(None)
    args = {"method": "GET", "path": "/serp/12/csv", "params": {"organic": True}}
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        ticket = (await client.call_tool("keysso_api", args)).data
        assert ticket["needs_operator_approval"] is True and source.calls == []
        approve(tmp_path, ticket)
        await client.call_tool("keysso_api", {**args, "approval_id": ticket["approval_id"]})
        await client.call_tool("keysso_api", {"method": "GET", "path": "/serp/12/csv/export-status"})
    assert [call[1].rsplit("/", 1)[-1] for call in source.calls] == ["csv", "export-status"]
    assert source.single == [True, False]  # the approved export gets exactly one upstream attempt


def test_api_request_is_bounded_before_an_approval_is_stored():
    with pytest.raises(ValueError, match="bytes"):
        validate_call("POST", "/tools/check-top", None, {"list": ["x" * 3_000_000]})
    with pytest.raises(ValueError, match="10000 items"):
        validate_call("POST", "/tools/check-top", None, {"base": "msk", "nested": {"list": [1] * 10_001}})
    with pytest.raises(ValueError, match="depth"):
        validate_call("POST", "/tools/check-top", None, {"a": [[[[[[[[["deep"]]]]]]]]]})
    assert validate_call("POST", "/tools/check-top", None, {"list": ["a"] * 10_000})[0] == "POST"


def test_pending_approvals_have_per_principal_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals_module, "MAX_PENDING_PER_PRINCIPAL", 2)
    store = ApprovalStore(tmp_path / "keysso-approvals.json")
    first = store.prepare("keysso_api", DELETE, "x", "alice", "bind")
    store.prepare("keysso_api", DELETE, "x", "alice", "bind")
    with pytest.raises(ApprovalQuotaExceeded):
        store.prepare("keysso_api", DELETE, "x", "alice", "bind")
    store.prepare("keysso_api", DELETE, "x", "bob", "bind")  # another principal is not starved
    store.accept(first["approval_id"], first["digest"])  # accepted no longer counts as pending
    store.prepare("keysso_api", DELETE, "x", "alice", "bind")
    monkeypatch.setattr(approvals_module, "MAX_STORE_BYTES", 10)
    with pytest.raises(ApprovalQuotaExceeded):
        store.prepare("keysso_api", DELETE, "x", "carol", "bind")


async def test_quota_error_is_a_safe_envelope(tmp_path, key_pair, monkeypatch):  # noqa: F811
    monkeypatch.setattr(approvals_module, "MAX_PENDING_PER_PRINCIPAL", 1)
    async with Client(server(tmp_path, key_pair, monkeypatch, Recorder({}))) as client:
        await client.call_tool("keysso_api", DELETE)
        with pytest.raises(ToolError, match="approval_quota_exceeded"):
            await client.call_tool("keysso_api", DELETE)


def test_monitoring_engines_follow_apidoc():
    """apidoc engine enum: 0 Yandex desktop, 1 Yandex mobile, 3 Google mobile, 4 Google desktop."""
    for engine in (0, 1, 3, 4):
        request = monitoring_write_request("start", project_id=5, engine=engine)
        assert request[3]["searchSettings"][0]["engine"] == engine
        params = monitoring_request("dates", project_id=5, region_id=213, engine=engine)[2]
        assert f'"engine":{engine}' in params["searchSettings[]"][0]
    for bad in (2, 5, -1, True):
        with pytest.raises(ValueError, match="Google desktop"):
            monitoring_write_request("start", project_id=5, engine=bad)


def test_tracking_item_accepts_urls():
    for item in (
        "example.com",
        "example.com/catalog",
        "https://example.com/page",
        "http://a.example.ru/x?y=1",
    ):
        assert (
            monitoring_write_request("create", tracking_item=item, cluster_uid="u1")[3]["trackingItem"]
            == item
        )
    for bad in (
        "ftp://example.com/x",
        "https://user:pw@example.com/",
        "javascript:alert(1)",
        "https:///x",
        "https://exa mple.com/",
        "https://example.com:99999/",
    ):
        with pytest.raises(ValueError):
            monitoring_write_request("create", tracking_item=bad, cluster_uid="u1")
