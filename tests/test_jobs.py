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
        done = (
            await client.call_tool(
                "keysso_clustering", {"action": "create", "phrases": ["a"], "confirm": True}
            )
        ).data
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
