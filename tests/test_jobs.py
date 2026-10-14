from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_server import configuration

from zai_keysso.adapter import KeysSoAdapter
from zai_keysso.jobs import (
    clustering_request,
    keyword_job_request,
    monitoring_request,
    monitoring_write_request,
)
from zai_keysso.server import AdmittedHttpClient, create_server


@pytest.fixture(scope="module")
def key_pair():
    return RSAKeyPair.generate()


class Recorder:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def factory(self, store, execution_id, actor, delegated):
        owner = self

        class Http(AdmittedHttpClient):
            async def request_json(self, method, url, **kwargs):
                await self._admit_attempt(1)
                owner.calls.append((method, url, kwargs.get("params"), kwargs.get("payload")))
                return owner.payload

        return Http(store, execution_id, actor, delegated)


def approve(tmp_path, ticket):
    from zai_keysso.approvals import ApprovalStore

    ApprovalStore(tmp_path / "keysso-approvals.json").accept(ticket["approval_id"], ticket["digest"])


def server(tmp_path, key_pair, monkeypatch, source=None):
    monkeypatch.setenv("KEYSSO_TOOLSETS", "all")
    config = configuration(tmp_path, key_pair, auth_mode="operator")
    return create_server(config, transport="stdio", http_factory=source.factory if source else None)


def test_keyword_job_requests():
    assert keyword_job_request("extended_keywords", "start", phrases=[" купить  диван ", "купить диван"]) == (
        "POST",
        "/tools/extended_keywords",
        {},
        {"list": ["купить диван"], "base": "msk"},
    )
    method, path, params, _ = keyword_job_request(
        "keywords_by_list", "result", uid="msk:44:abc", per_page=500
    )
    assert (method, path, params) == (
        "GET",
        "/tools/keywords_by_list/msk:44:abc",
        {"per_page": 500, "base": "msk"},
    )
    assert keyword_job_request("concurents_by_keywords", "start", phrases=["a"], top=50)[3]["top"] == 50
    with pytest.raises(ValueError):
        keyword_job_request("extended_keywords", "status", uid="../x")
    with pytest.raises(ValueError):
        keyword_job_request("extended_keywords", "start", phrases=["x" * 101])


def test_clustering_and_monitoring_requests():
    assert clustering_request("build", uid="u1", top_number=20, min_frequency=10)[3]["fWsk"] == 10
    assert clustering_request("keywords", uid="u1", folder_id=7)[1] == "/clustering/node/u1/7/keywords"
    method, path, params, _ = monitoring_request(
        "report", project_id=5, date_from="2026-10-01", date_to="2026-10-08", region_id=213, engine=0
    )
    assert path == "/monitoring/5/report" and params["dateFrom"] == "2026-10-01"
    assert params["searchSettings[]"] == ['{"regionId":213,"engine":0}']
    with pytest.raises(ValueError):
        monitoring_request("report", project_id=5)
    created = monitoring_write_request("create", tracking_item="example.com", cluster_uid="u1")
    assert created[3]["clusterUuid"] == "u1" and created[1] == "/monitoring"


def test_new_report_paths_are_allowlisted():
    KeysSoAdapter.validate(
        "/report/simple/organic/keywords/bypage", {"page_url": "https://example.com/a", "base": "msk"}
    )
    # apidoc names the parameter page_url; a bare url would be silently ignored upstream.
    with pytest.raises(ValueError):
        KeysSoAdapter.validate(
            "/report/simple/organic/concurent_pages",
            {"url": "https://example.com/a", "domain": "example.com"},
        )
    KeysSoAdapter.validate("/report/group/organic/keywords/abc123", {"page": 1})
    KeysSoAdapter.validate("/robots/data", {"domain": "example.com", "date": "2026-10-01"})
    with pytest.raises(ValueError):
        KeysSoAdapter.validate("/report/group/../../admin/x", {})


async def test_start_needs_confirm_and_spends_nothing_without_it(tmp_path, key_pair, monkeypatch):
    source = Recorder({"uid": "msk:1:abc"})
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        preview = (
            await client.call_tool("keysso_clustering", {"action": "create", "phrases": ["a", "b"]})
        ).data
        assert preview["needs_confirmation"] is True and preview["phrases"] == 2 and source.calls == []
        args = {"action": "create", "phrases": ["a"], "confirm": True}
        ticket = (await client.call_tool("keysso_clustering", args)).data
        assert ticket["needs_operator_approval"] is True and source.calls == []
        approve(tmp_path, ticket)
        done = (
            await client.call_tool("keysso_clustering", {**args, "approval_id": ticket["approval_id"]})
        ).data
        with pytest.raises(Exception, match="not accepted"):  # single use
            await client.call_tool("keysso_clustering", {**args, "approval_id": ticket["approval_id"]})
    assert done["payload"]["uid"] == "msk:1:abc"
    assert source.calls[0][0] == "POST" and source.calls[0][1].endswith("/clustering")


async def test_reads_do_not_need_confirm(tmp_path, key_pair, monkeypatch):
    source = Recorder({"items": []})
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        await client.call_tool("keysso_monitoring", {"action": "projects"})
        await client.call_tool(
            "keysso_keyword_job", {"kind": "extended_keywords", "action": "status", "uid": "x1"}
        )
    assert [call[0] for call in source.calls] == ["GET", "GET"]
    assert source.calls[1][1].endswith("/tools/extended_keywords/state/x1")


def test_concurents_result_view_and_base_match_apidoc():
    from zai_keysso.jobs import keyword_job_request

    _m, path, params, _p = keyword_job_request(
        "concurents_by_keywords", "result", uid="abc", base="spb", view="context"
    )
    assert path == "/tools/concurents_by_keywords/abc" and params == {"base": "spb", "view": "context"}
    for bad in ("domains", "urls"):
        with pytest.raises(ValueError):
            keyword_job_request("concurents_by_keywords", "result", uid="abc", view=bad)
    with pytest.raises(ValueError):
        keyword_job_request("concurents_by_keywords", "start", phrases=["a"], top=20)


def test_extended_keywords_similarity_config_and_top_number():
    from zai_keysso.jobs import clustering_request, keyword_job_request

    _m, _path, _q, payload = keyword_job_request("extended_keywords", "start", phrases=["a"], similarity=40)
    assert payload["config"] == {"similarity": 40, "deleteDuplicate": True, "additions": False}
    with pytest.raises(ValueError):
        keyword_job_request("extended_keywords", "start", phrases=["a"], similarity=2)
    with pytest.raises(ValueError):
        keyword_job_request("keywords_by_list", "start", phrases=["a"], similarity=40)
    with pytest.raises(ValueError):
        clustering_request("build", uid="u1", top_number=30)


async def test_api_reads_run_and_writes_need_operator_approval(tmp_path, key_pair, monkeypatch):
    source = Recorder({"status": "ok"})
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        await client.call_tool("keysso_api", {"method": "GET", "path": "/serp/12/status"})
        assert source.calls[-1][0] == "GET" and source.calls[-1][1].endswith("/serp/12/status")
        args = {"method": "PATCH", "path": "/monitoring/7", "body": {"name": "new"}}
        ticket = (await client.call_tool("keysso_api", args)).data
        assert ticket["needs_operator_approval"] and len(source.calls) == 1
        with pytest.raises(Exception, match="not accepted"):
            await client.call_tool("keysso_api", {**args, "approval_id": ticket["approval_id"]})
        approve(tmp_path, ticket)
        with pytest.raises(Exception, match="exact request"):
            await client.call_tool(
                "keysso_api", {**args, "body": {"name": "other"}, "approval_id": ticket["approval_id"]}
            )
        # a mismatched attempt does not burn the approval
        await client.call_tool("keysso_api", {**args, "approval_id": ticket["approval_id"]})
        assert source.calls[-1][:2] == ("PATCH", source.calls[-1][1]) and source.calls[-1][3] == {
            "name": "new"
        }
        with pytest.raises(Exception, match="allowlist"):
            await client.call_tool("keysso_api", {"method": "DELETE", "path": "/limits/all"})


def test_api_allowlist_matches_apidoc_paths():
    from zai_keysso.api_calls import validate_call

    assert validate_call("post", "tools/check-top", {"base": "msk"}, {"list": ["a"]})[1] == "/tools/check-top"
    assert validate_call("DELETE", "/clustering/msk:1:abc", None, None)[0] == "DELETE"
    for bad in (("GET", "/serp/../limits"), ("PUT", "/monitoring/1"), ("POST", "/monitoring/x/start")):
        with pytest.raises(ValueError):
            validate_call(*bad, None, None)
    with pytest.raises(ValueError, match="GET takes no body"):
        validate_call("GET", "/serp", None, {"a": 1})


def test_report_filter_parameter_is_passed_through():
    path, params = KeysSoAdapter.validate(
        "/report/simple/organic/keywords", {"domain": "a.ru", "filter": "wsk>10"}
    )
    assert params["filter"] == "wsk>10"
    with pytest.raises(ValueError):
        KeysSoAdapter.validate("/report/simple/organic/keywords", {"domain": "a.ru", "filter": 5})


def test_concurrent_accept_cannot_resurrect_a_consumed_approval(tmp_path, monkeypatch):
    """Server and operator CLI share one file: a stale operator write must not re-arm a spent approval."""
    import threading
    import time

    from zai_keysso.approvals import ApprovalStore

    store = ApprovalStore(tmp_path / "keysso-approvals.json")
    spent = {"method": "POST", "path": "/clustering", "params": {}, "payload": {"list": ["a"]}}
    x = store.prepare("keysso_clustering", spent, "POST /clustering")
    y = store.prepare("keysso_api", {"method": "DELETE", "path": "/serp/1"}, "DELETE /serp/1")
    store.accept(x["approval_id"], x["digest"])
    loaded, original = threading.Event(), ApprovalStore._load

    def slow_load(self):
        data = original(self)
        if threading.current_thread().name == "operator":
            loaded.set()
            time.sleep(0.3)  # the operator CLI read is in flight while the server consumes
        return data

    monkeypatch.setattr(ApprovalStore, "_load", slow_load)
    operator = threading.Thread(target=store.accept, args=(y["approval_id"], y["digest"]), name="operator")
    operator.start()
    assert loaded.wait(5)
    store.consume(x["approval_id"], "keysso_clustering", spent)
    operator.join()
    with pytest.raises(PermissionError):  # still single use
        store.consume(x["approval_id"], "keysso_clustering", spent)
    assert [item["approval_id"] for item in store.pending()] == []  # y was accepted, not lost


async def test_operator_command_works_from_any_directory(tmp_path, key_pair, monkeypatch, capsys):
    import shlex
    from pathlib import Path

    from zai_keysso import approvals

    source = Recorder({"uid": "msk:1:abc"})
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        args = {"action": "create", "phrases": ["купить диван"], "confirm": True}
        ticket = (await client.call_tool("keysso_clustering", args)).data
        command = shlex.split(ticket["operator_command"])
        assert command[0] == "keysso-approval"
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)  # operator shell: other cwd, no KEYSSO_STATE_PATH
        default = Path("state/keysso-approvals.json")
        path = command[command.index("--path") + 1]
        assert approvals.main(["--path", path, "--list"], default_path=default) == 0
        listed = capsys.readouterr().out
        assert "купить диван" in listed and ticket["digest"] in listed  # operator sees the payload
        assert approvals.main(command[1:], default_path=default) == 0
        await client.call_tool("keysso_clustering", {**args, "approval_id": ticket["approval_id"]})
    assert source.calls[-1][0] == "POST" and source.calls[-1][3]["list"] == ["купить диван"]
    assert not (elsewhere / "state").exists()


async def test_invalid_confirmed_start_returns_validation_envelope(tmp_path, key_pair, monkeypatch):
    source = Recorder({})
    async with Client(server(tmp_path, key_pair, monkeypatch, source)) as client:
        with pytest.raises(Exception, match="validation_failed"):
            await client.call_tool("keysso_clustering", {"action": "create", "phrases": [], "confirm": True})
    assert source.calls == []


def test_api_rejects_dot_segments_that_http_clients_collapse():
    from zai_keysso.api_calls import validate_call

    for path in ("/tools/extended_keywords/..", "/clustering/node/.", "/clustering/../update-frequency"):
        with pytest.raises(ValueError, match="allowlist"):
            validate_call("GET", path, None, None)
    with pytest.raises(ValueError, match="allowlist"):
        validate_call("DELETE", "/clustering/..", None, None)
    assert validate_call("GET", "/clustering/node/msk:1.2_a", None, None)[1] == "/clustering/node/msk:1.2_a"
