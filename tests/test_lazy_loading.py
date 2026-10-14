"""KEYSSO_TOOL_LOADING=lazy: small start surface, runtime toolset enabling, list_changed."""

from __future__ import annotations

import json

import mcp.types
import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_server import configuration

from zai_keysso.lazy_loading import estimate_tokens
from zai_keysso.server import create_server

ENV = "KEYSSO"
ENABLE = "keysso_enable_toolsets"
CORE = {"keysso_check_update", "keysso_limits", "keysso_domain_report", ENABLE}
LAZY_BUDGET_TOKENS = 1_200


@pytest.fixture(scope="module")
def key_pair():
    return RSAKeyPair.generate()


def build(tmp_path, key_pair):
    return create_server(configuration(tmp_path, key_pair, auth_mode="operator"), transport="stdio")


async def startup_tokens(client: Client) -> int:
    tools = await client.list_tools()
    listed = [tool.model_dump(mode="json", exclude_none=True) for tool in tools]
    return estimate_tokens(listed) + estimate_tokens(client.initialize_result.instructions or "")


class Notices:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def __call__(self, message) -> None:
        root = getattr(message, "root", message)
        if isinstance(root, mcp.types.ToolListChangedNotification):
            self.seen.append("tools/list_changed")


async def test_eager_is_default_and_unchanged(tmp_path, key_pair, monkeypatch):
    monkeypatch.delenv(f"{ENV}_TOOL_LOADING", raising=False)
    async with Client(build(tmp_path, key_pair)) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert ENABLE not in names
        assert "Lazy tools" not in (client.initialize_result.instructions or "")


async def test_lazy_start_surface(tmp_path, key_pair, monkeypatch):
    monkeypatch.setenv(f"{ENV}_TOOL_LOADING", "lazy")
    async with Client(build(tmp_path, key_pair)) as client:
        assert client.initialize_result.capabilities.tools.listChanged is True
        assert {tool.name for tool in await client.list_tools()} == CORE
        assert f"{ENABLE}()" in client.initialize_result.instructions
        listing = (await client.call_tool(ENABLE, {})).data
    assert listing["mode"] == "lazy"
    assert {row["toolset"] for row in listing["toolsets"]} >= {"reports", "ai_tracker"}
    assert all(row["description"] and row["token_cost"] > 0 for row in listing["toolsets"])


async def test_enable_registers_tools_and_notifies(tmp_path, key_pair, monkeypatch):
    monkeypatch.setenv(f"{ENV}_TOOL_LOADING", "lazy")
    notices = Notices()
    async with Client(build(tmp_path, key_pair), message_handler=notices) as client:
        result = (await client.call_tool(ENABLE, {"toolsets": ["reports"]})).data
        names = {tool.name for tool in await client.list_tools()}
    assert set(result["added_tools"]) == {"keysso_compare_domains", "keys_so_query"}
    assert names == CORE | {"keysso_compare_domains", "keys_so_query"}
    assert notices.seen == ["tools/list_changed"]
    assert "reconnect" in result["hint"]


async def test_enable_is_idempotent(tmp_path, key_pair, monkeypatch):
    monkeypatch.setenv(f"{ENV}_TOOL_LOADING", "lazy")
    notices = Notices()
    async with Client(build(tmp_path, key_pair), message_handler=notices) as client:
        await client.call_tool(ENABLE, {"toolsets": ["ai_tracker"]})
        again = (await client.call_tool(ENABLE, {"toolsets": ["ai_tracker"]})).data
        names = [tool.name for tool in await client.list_tools()]
    assert again["added_tools"] == [] and again["already_enabled"] is True
    assert names.count("keysso_ai_tracker") == 1
    assert notices.seen == ["tools/list_changed"]


async def test_lazy_respects_allowlist_and_read_only(tmp_path, key_pair, monkeypatch):
    monkeypatch.setenv(f"{ENV}_TOOL_LOADING", "lazy")
    monkeypatch.setenv(f"{ENV}_TOOLSETS", "all")
    monkeypatch.setenv(f"{ENV}_READ_ONLY", "1")
    async with Client(build(tmp_path, key_pair)) as client:
        listing = (await client.call_tool(ENABLE, {})).data
        everything = (await client.call_tool(ENABLE, {"toolsets": ["all"]})).data
        tools = await client.list_tools()
    assert "jobs" not in {row["toolset"] for row in listing["toolsets"]}
    assert all(tool.annotations.readOnlyHint for tool in tools)
    assert "keysso_keyword_job" not in everything["added_tools"]
    monkeypatch.setenv(f"{ENV}_READ_ONLY", "0")
    monkeypatch.setenv(f"{ENV}_TOOLSETS", "default")
    async with Client(build(tmp_path, key_pair)) as client:
        refused = (await client.call_tool(ENABLE, {"toolsets": ["jobs"]})).data
    assert refused["error"] == "unknown_toolset"


def test_invalid_mode_is_rejected(tmp_path, key_pair, monkeypatch):
    monkeypatch.setenv(f"{ENV}_TOOL_LOADING", "sometimes")
    with pytest.raises(ValueError):
        build(tmp_path, key_pair)


async def test_lazy_startup_budget(tmp_path, key_pair, monkeypatch, capsys):
    costs = {}
    for mode in ("eager", "lazy"):
        monkeypatch.setenv(f"{ENV}_TOOL_LOADING", mode)
        async with Client(build(tmp_path / mode, key_pair)) as client:
            costs[mode] = await startup_tokens(client)
    assert costs["lazy"] <= LAZY_BUDGET_TOKENS
    assert costs["lazy"] < costs["eager"]
    with capsys.disabled():
        print(f"\nstartup tokens {json.dumps(costs)}")


@pytest.mark.parametrize(("answer", "mode"), [("lazy", "lazy"), ("", "eager"), ("whatever", "eager")])
def test_setup_wizard_asks_eager_or_lazy(answer, mode, monkeypatch):
    from zai_keysso import setup

    asked = []

    def fake_input(prompt):
        asked.append(prompt)
        return answer

    monkeypatch.setattr("builtins.input", fake_input)
    assert setup._tool_loading() == mode
    assert "lazy" in asked[0] and "eager" in asked[0]
