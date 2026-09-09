from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from zai_keysso.policy import PolicyStore
from zai_keysso.server import AdmittedHttpClient
from zai_keysso.transport import ProviderAdmissionDenied, ProviderTransientHttpError, RetryPolicy


@pytest.mark.parametrize("delegated,expected_attempts", [(True, 1), (False, 3)])
async def test_actual_http_attempts_are_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delegated: bool, expected_attempts: int
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": "temporary"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "zai_keysso.transport.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    store = PolicyStore(tmp_path / "state.sqlite", "default", 10, 10)
    store.begin("execution", "request", "alice", "hash")
    client = AdmittedHttpClient(store, "execution", "alice", delegated)
    client.retry = RetryPolicy(attempts=1 if delegated else 3, base_delay_seconds=0)
    with pytest.raises(ProviderTransientHttpError):
        await client.request_json("GET", "https://api.keys.so/limits/all")
    assert len(calls) == expected_attempts
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == expected_attempts


async def test_retry_is_denied_before_second_network_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": "temporary"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "zai_keysso.transport.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    store = PolicyStore(tmp_path / "state.sqlite", "default", 1, 1)
    store.begin("execution", "request", "alice", "hash")
    client = AdmittedHttpClient(store, "execution", "alice", delegated=False)
    client.retry = RetryPolicy(attempts=3, base_delay_seconds=0)
    with pytest.raises(ProviderAdmissionDenied):
        await client.request_json("GET", "https://api.keys.so/limits/all")
    assert len(calls) == 1
