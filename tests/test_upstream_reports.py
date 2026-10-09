from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_server import Recorder, configuration

from zai_keysso.adapter import KeysSoAdapter
from zai_keysso.ai_tracker import REPORTS, ai_tracker_request
from zai_keysso.server import create_server


@pytest.mark.parametrize(
    "path,params",
    [
        ("/report/simple/context/ads/archive", {"domain": "example.com", "month": "2026-09", "full": True}),
        ("/report/simple/context/ads/archive/months", {"domain": "example.com", "base": "msk"}),
        ("/report/simple/context/keywords/archive", {"domain": "example.com", "sort": "wsk|desc"}),
        ("/report/simple/context/keywords/byads/archive", {"domain": "example.com", "ads_id": "7"}),
        ("/report/simple/context/keyword/ads/archive", {"keyword": "купить телефон", "sort": "keyscnt|desc"}),
        ("/report/simple/context/keyword/ads/archive/months", {"keyword": "купить телефон"}),
        ("/report/simple/keyword_dashboard", {"keyword": "пластиковые окна", "base": "msk"}),
        ("/report/simple/similarkeys", {"keyword": "пластиковые окна", "sort": "wsk|asc,ws|desc"}),
    ],
)
def test_new_keysso_reports_are_allowed(path, params):
    normalized, validated = KeysSoAdapter.validate(path, params)
    assert normalized == path
    if "full" in params:
        assert validated["full"] == 1


@pytest.mark.parametrize(
    "path,params",
    [
        ("/report/simple/context/keywords", {"domain": "example.com", "sort": "txt|asc"}),
        ("/report/simple/context/keywords/byads", {"domain": "example.com", "sort": "pos|asc,url|desc"}),
        ("/report/simple/context/keywords/archive", {"domain": "example.com", "sort": "header|desc"}),
        ("/report/simple/context/keyword/ads/archive", {"keyword": "x", "sort": "pos|asc"}),
        ("/report/simple/context/ads/archive", {"domain": "example.com", "month": "2026-13"}),
        ("/report/simple/context/ads/archive", {"domain": "example.com", "month": "09.2026"}),
        ("/report/simple/context/ads/archive", {"domain": "example.com", "full": "yes"}),
        ("/report/simple/keyword_dashboard", {"keyword": "   "}),
        ("/report/simple/keyword_dashboard", {"keyword": "x" * 513}),
        ("/report/simple/similarkeys", {"keyword": "x", "sort": "a|asc,b|asc,c|asc,d|asc"}),
    ],
)
def test_provider_rejected_sorts_and_bad_archive_params_fail_locally(path, params):
    with pytest.raises(ValueError):
        KeysSoAdapter.validate(path, params)


def test_ai_tracker_request_builds_bracket_arrays():
    path, params = ai_tracker_request(
        "report",
        42,
        date_from="2026-10-01",
        date_to="2026-10-07",
        systems=[6, 3, 6],
        groups=["— без группы —"],
        page=1,
        per_page=25,
    )
    assert path == "/ai_tracker/42/report"
    assert params == {
        "systems[]": [3, 6],
        "groups[]": ["— без группы —"],
        "date_from": "2026-10-01",
        "date_to": "2026-10-07",
        "page": 1,
        "per_page": 25,
    }
    assert ai_tracker_request("projects", search="brand") == ("/ai_tracker", {"search": "brand"})
    assert ai_tracker_request("prompt", 42, prompt_id=5, date="2026-10-01")[1] == {
        "date": "2026-10-01",
        "prompt_id": "5",
    }


@pytest.mark.parametrize(
    "report,tracker_id,kwargs",
    [
        ("start", 1, {}),
        ("report", None, {}),
        ("projects", 1, {}),
        ("entity", 1, {"search": "x"}),
        ("report", 1, {"date_from": "2026-10-07", "date_to": "2026-10-01"}),
        ("report", 1, {"systems": ["6"]}),
        ("sources", 1, {"view": "page"}),
        ("prompt", 1, {"prompt_id": 5}),
        ("mentions", 1, {"per_page": 501}),
        ("report", True, {}),
    ],
)
def test_invalid_ai_tracker_requests_fail_locally(report, tracker_id, kwargs):
    with pytest.raises(ValueError):
        ai_tracker_request(report, tracker_id, **kwargs)


def test_ai_tracker_surface_is_get_only():
    assert all(path.startswith("/ai_tracker") for path, _ in REPORTS.values())
    assert not any(word in path for path, _ in REPORTS.values() for word in ("start", "prompts", "brand"))


async def test_ai_tracker_tool_reads_through_admitted_client(tmp_path: Path):
    recorder = Recorder({"data": []})
    config = configuration(tmp_path, RSAKeyPair.generate(), auth_mode="operator")
    server = create_server(config, transport="stdio", http_factory=recorder.factory)
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        for tool in tools.values():
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False
        result = await client.call_tool(
            "keysso_ai_tracker", {"report": "sources", "tracker_id": 9, "view": "domain", "systems": [6]}
        )
        assert result.data == {"payload": {"data": []}}
        with pytest.raises(ToolError, match="validation_failed"):
            await client.call_tool("keysso_ai_tracker", {"report": "sources"})
    assert recorder.calls == [
        {
            "method": "GET",
            "url": "https://api.keys.so/ai_tracker/9/sources",
            "params": {"systems[]": [6], "view": "domain"},
        }
    ]
