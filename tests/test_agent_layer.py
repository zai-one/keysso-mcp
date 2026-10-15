from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_reports import Pages, page
from test_server import configuration

from zai_keysso import reports
from zai_keysso.agent_layer import DESCRIPTION_LIMIT, INSTRUCTIONS_LIMIT
from zai_keysso.agent_profile import PROFILE
from zai_keysso.server import create_server

ROOT = Path(__file__).resolve().parents[1]
TOOLS_LIST_BUDGET = 12_000


@pytest.fixture(scope="module")
def key_pair():
    return RSAKeyPair.generate()


def server(tmp_path, key_pair, source=None):
    config = configuration(tmp_path, key_pair, auth_mode="operator")
    return create_server(config, transport="stdio", http_factory=source.factory if source else None)


async def test_token_budget_and_agent_surface(tmp_path, key_pair):
    async with Client(server(tmp_path, key_pair)) as client:
        assert len(client.initialize_result.instructions or "") <= INSTRUCTIONS_LIMIT
        tools = await client.list_tools()
        default = {n for ts, group in PROFILE.toolsets.items() if ts not in PROFILE.optin for n in group}
        assert {tool.name for tool in tools} == default
        for tool in tools:
            assert tool.title and len(tool.description or "") <= DESCRIPTION_LIMIT
        assert len(json.dumps([tool.model_dump(exclude_none=True) for tool in tools])) <= TOOLS_LIST_BUDGET
        uris = {str(item.uri) for item in await client.list_resources()}
        assert {"keysso://reports", "keysso://playbook", "keysso://toolsets"} <= uris
        assert "vis" in (await client.read_resource("keysso://guide/metrics-glossary"))[0].text
        assert {p.name for p in await client.list_prompts()} == {
            "competitor_research",
            "content_gap",
            "phrase_report",
            "semantic_core",
        }


async def test_toolsets_filter(tmp_path, key_pair, monkeypatch):
    monkeypatch.setenv("KEYSSO_TOOLSETS", "ai_tracker")
    async with Client(server(tmp_path, key_pair)) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {"keysso_ai_tracker", "keysso_check_update", "keysso_limits"}


async def test_limits_tool_calls_limits_all(tmp_path, key_pair):
    source = Pages([{"tools": [{"name": "domain", "left": 10}]}])
    async with Client(server(tmp_path, key_pair, source)) as client:
        result = (await client.call_tool("keysso_limits", {})).data
    assert result["payload"]["tools"][0]["left"] == 10
    assert source.calls[0][0].endswith("/limits/all") and source.calls[0][1] == {}


async def test_fields_projection_trims_rows():
    result = await reports.collect_report(
        Pages([page(1), page(2)]),
        "/report/simple/organic/keywords",
        {"domain": "example.com"},
        start_page=1,
        max_pages=5,
        page_size=2,
        output="json",
        fields=["word"],
    )
    assert result["rows"] == [{"word": "keyword-0"}, {"word": "keyword-1"}, {"word": "keyword-2"}]
    assert "missing_fields" not in result
    typo = await reports.collect_report(
        Pages([page(1), page(2)]),
        "/report/simple/organic/keywords",
        {"domain": "example.com"},
        start_page=1,
        max_pages=5,
        page_size=2,
        output="json",
        fields=["word", "wrod"],
    )
    assert typo["missing_fields"] == ["wrod"]
    with pytest.raises(ValueError):
        reports.validate_fields(["bad field!"])


def test_static_budget_script_passes():
    sys.path.insert(0, str(ROOT / "scripts"))
    import token_budget

    assert token_budget.problems() == []
