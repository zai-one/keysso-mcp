from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError


async def test_installed_stdio_from_unrelated_directory(tmp_path: Path) -> None:
    token = tmp_path / "synthetic.token"
    token.write_text("synthetic-entrypoint-credential", encoding="utf-8")
    token.chmod(0o600)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "zai_keysso", "--transport", "stdio"],
        env={
            "KEYSSO_API_TOKEN_FILE": str(token),
            "KEYSSO_STATE_PATH": str(tmp_path / "state.sqlite"),
            "KEYSSO_AUTH_MODE": "operator",
        },
        cwd=str(tmp_path),
        keep_alive=False,
    )
    async with Client(transport, timeout=30) as client:
        assert [tool.name for tool in await client.list_tools()] == ["keys_so_query"]
        # A forbidden report proves the installed entrypoint executes its policy
        # without consuming provider quota or needing a real credential.
        with pytest.raises(ToolError, match="validation_failed"):
            await client.call_tool("keys_so_query", {"path": "/admin/delete", "params": {}})
