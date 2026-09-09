from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from zai_keysso.config import ServiceConfig
from zai_keysso.server import AdmittedHttpClient, create_server
from zai_keysso.transport import ProviderRateLimited, request_hash

ARGS = {"path": "/limits/all", "params": {}}
FAKE_SECRET = "synthetic-provider-credential-not-live"
CONTRACT = json.loads((Path(__file__).resolve().parents[1] / "contracts/keys_so_query.json").read_text())


@pytest.fixture(scope="module")
def key_pair() -> RSAKeyPair:
    return RSAKeyPair.generate()


def configuration(tmp_path: Path, key_pair: RSAKeyPair, **changes: Any) -> ServiceConfig:
    config = ServiceConfig(
        provider_token=FAKE_SECRET,
        state_path=tmp_path / "state.sqlite",
        public_key=key_pair.public_key,
        issuer="fixture",
        audience="keysso-mcp",
        auth_mode="delegated",
    )
    return replace(config, **changes)


def bearer(key_pair: RSAKeyPair, args: dict[str, Any] | None = None, **claims: Any) -> str:
    extra = {
        "account_id": "default",
        "jti": uuid4().hex,
        "request_id": uuid4().hex,
        "tool": "keys_so_query",
        "request_hash": request_hash(args or ARGS),
    }
    extra.update(claims)
    return key_pair.create_token(
        subject="alice",
        issuer="fixture",
        audience="keysso-mcp",
        scopes=["keys_so:read"],
        expires_in_seconds=45,
        additional_claims=extra,
    )


class Recorder:
    def __init__(self, payload: Any = None, failure: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self.payload = {"remaining": 42} if payload is None else payload
        self.failure = failure

    def factory(self, store: Any, execution_id: str, actor: str, delegated: bool) -> Any:
        recorder = self

        class Http(AdmittedHttpClient):
            async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
                await self._admit_attempt(1)
                recorder.calls.append({"method": method, "url": url, "params": kwargs.get("params")})
                if recorder.failure:
                    raise recorder.failure
                return recorder.payload

        return Http(store, execution_id, actor, delegated)


@asynccontextmanager
async def connection(server: Any, token: str):
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("verify", None)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture", **kwargs)

    transport = StreamableHttpTransport("http://fixture/mcp", auth=token, httpx_client_factory=factory)
    async with app.router.lifespan_context(app), Client(transport) as client:
        yield client


async def test_authenticated_http_contract_and_replay(tmp_path: Path, key_pair: RSAKeyPair) -> None:
    config = configuration(tmp_path, key_pair)
    recorder = Recorder([{"domain": "example.com"}])
    server = create_server(config, http_factory=recorder.factory)
    token = bearer(key_pair)
    async with connection(server, token) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["keys_so_query"]
        assert tools[0].inputSchema == CONTRACT["inputSchema"]
        assert tools[0].outputSchema == CONTRACT["outputSchema"]
        assert (await client.call_tool("keys_so_query", ARGS)).data == {
            "payload": [{"domain": "example.com"}]
        }
        with pytest.raises(ToolError, match="provider_disabled"):
            await client.call_tool("keys_so_query", ARGS)
    # Same nonce is also rejected by a restarted service using the same ledger.
    async with connection(create_server(config, http_factory=recorder.factory), token) as client:
        with pytest.raises(ToolError, match="provider_disabled"):
            await client.call_tool("keys_so_query", ARGS)
    assert len(recorder.calls) == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"account_id": "other"},
        {"request_hash": "wrong"},
        {"tool": "unknown"},
        {"jti": ""},
        {"request_id": ""},
        {"exp": int(time.time()) + 3600},
        {"iat": 0},
    ],
)
async def test_bad_delegation_never_reaches_provider(
    tmp_path: Path, key_pair: RSAKeyPair, claims: dict[str, Any]
) -> None:
    recorder = Recorder()
    server = create_server(configuration(tmp_path, key_pair), http_factory=recorder.factory)
    async with connection(server, bearer(key_pair, **claims)) as client:
        with pytest.raises(ToolError, match="provider_disabled"):
            await client.call_tool("keys_so_query", ARGS)
    assert recorder.calls == []


@pytest.mark.parametrize("token_kind", ["missing", "bad_signature", "scope", "audience", "expired"])
async def test_http_authentication_is_required(tmp_path: Path, key_pair: RSAKeyPair, token_kind: str) -> None:
    token = {
        "missing": "",
        "bad_signature": "not-a-token",
        "scope": bearer(key_pair, scope="system:read"),
        "audience": bearer(key_pair, aud="other-service"),
        "expired": bearer(key_pair, exp=1),
    }[token_kind]
    recorder = Recorder()
    server = create_server(configuration(tmp_path, key_pair), http_factory=recorder.factory)
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client,
    ):
        response = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
            },
        )
        assert response.status_code in {401, 403}
    assert recorder.calls == []


async def test_validation_and_secret_redaction(tmp_path: Path, key_pair: RSAKeyPair) -> None:
    recorder = Recorder({"innocent": f"echo {FAKE_SECRET}", "token": FAKE_SECRET, "rows": [42]})
    config = configuration(tmp_path, key_pair, auth_mode="operator")
    server = create_server(config, transport="stdio", http_factory=recorder.factory)
    async with Client(server) as client:
        with pytest.raises(ToolError, match="validation_failed"):
            await client.call_tool("keys_so_query", {"path": "/admin/delete", "params": {}})
        result = (await client.call_tool("keys_so_query", ARGS)).data
        assert result == {
            "payload": {"innocent": "echo ***redacted***", "token": "***redacted***", "rows": [42]}
        }
    assert len(recorder.calls) == 1
    assert FAKE_SECRET.encode() not in config.state_path.read_bytes()


async def test_upstream_cooldown_and_safe_error(tmp_path: Path, key_pair: RSAKeyPair) -> None:
    recorder = Recorder(failure=ProviderRateLimited(FAKE_SECRET, retry_after_seconds=3600))
    config = configuration(tmp_path, key_pair)
    server = create_server(config, http_factory=recorder.factory)
    for _ in range(2):
        async with connection(server, bearer(key_pair)) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool("keys_so_query", ARGS)
            assert FAKE_SECRET not in str(caught.value)
            assert "provider_rate_limited" in str(caught.value)
    assert len(recorder.calls) == 1
    with sqlite3.connect(config.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_config_cannot_open_unauthenticated_http(tmp_path: Path, key_pair: RSAKeyPair) -> None:
    config = configuration(tmp_path, key_pair)
    with pytest.raises(ValueError, match="RSA public key"):
        create_server(replace(config, public_key=""))
    with pytest.raises(ValueError, match="delegated mode"):
        create_server(config, transport="stdio")
    with pytest.raises(ValueError, match="HTTPS origin"):
        replace(config, base_url="http://attacker.invalid")


async def test_deadline_cancels_upstream_before_releasing_lease(
    tmp_path: Path, key_pair: RSAKeyPair, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = asyncio.Event()
    monkeypatch.setattr("zai_keysso.server.OPERATION_TIMEOUT_SECONDS", 0.1)

    class SlowHttp(AdmittedHttpClient):
        async def request_json(self, *args: Any, **kwargs: Any) -> Any:
            await self._admit_attempt(1)
            try:
                await asyncio.sleep(5)
                return {"ok": True}
            finally:
                stopped.set()

    server = create_server(
        configuration(tmp_path, key_pair, auth_mode="operator"), transport="stdio", http_factory=SlowHttp
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="provider_timeout"):
            await client.call_tool("keys_so_query", ARGS)
        assert stopped.is_set(), "deadline released the lease while shielded upstream work was still running"


async def test_caller_cancellation_stops_upstream_and_finishes_audit(
    tmp_path: Path, key_pair: RSAKeyPair
) -> None:
    started, stopped = asyncio.Event(), asyncio.Event()
    config = configuration(tmp_path, key_pair, auth_mode="operator")

    class SlowHttp(AdmittedHttpClient):
        async def request_json(self, *args: Any, **kwargs: Any) -> Any:
            await self._admit_attempt(1)
            started.set()
            try:
                await asyncio.sleep(5)
                return {"ok": True}
            finally:
                stopped.set()

    server = create_server(config, transport="stdio", http_factory=SlowHttp)
    tool = await server.get_tool("keys_so_query")
    task = asyncio.create_task(tool.fn(**ARGS))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with sqlite3.connect(config.state_path) as db:
        assert db.execute("SELECT outcome FROM calls").fetchone()[0] == "cancelled"
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
    assert stopped.is_set()
