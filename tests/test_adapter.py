from __future__ import annotations

import asyncio
from typing import Any

import pytest

from zai_keysso import __version__
from zai_keysso.adapter import KeysSoAdapter
from zai_keysso.transport import ProviderError


class RecordingHttp:
    def __init__(self, response: Any = None) -> None:
        self.response = {"ok": True} if response is None else response
        self.calls: list[tuple[str, str, dict[str, str], dict[str, Any] | None]] = []

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        assert payload is None
        self.calls.append((method, url, headers or {}, params))
        return self.response


@pytest.mark.asyncio
async def test_keys_so_read_contract_uses_server_credential_and_preserves_list() -> None:
    http = RecordingHttp([{"domain": "example.com"}])
    adapter = KeysSoAdapter("https://api.keys.so", "secret", http=http)

    result = await adapter.query(
        "/report/simple/organic/keywords",
        {"base": "msk", "domain": "Example.com", "page": 1, "per_page": 25, "sort": "pos|asc"},
    )

    assert result == [{"domain": "example.com"}]
    assert http.calls == [
        (
            "GET",
            "https://api.keys.so/report/simple/organic/keywords",
            {
                "Accept": "application/json",
                "X-Keyso-TOKEN": "secret",
                "User-Agent": f"ZAI-ONE-Keysso-MCP/{__version__}",
            },
            {"base": "msk", "domain": "example.com", "page": 1, "per_page": 25, "sort": "pos|asc"},
        )
    ]


@pytest.mark.asyncio
async def test_keys_so_rejects_path_param_and_domain_escape_before_network() -> None:
    http = RecordingHttp()
    adapter = KeysSoAdapter("https://api.keys.so", "secret", http=http)

    with pytest.raises(ValueError, match="path is not allowed"):
        await adapter.query("/admin/tokens", {})
    with pytest.raises(ValueError, match="unsupported Keys.so parameters"):
        await adapter.query("/limits/all", {"url": "https://attacker.invalid"})
    with pytest.raises(ValueError, match="valid DNS domains"):
        await adapter.query("/report/simple/domain_dashboard", {"domain": "../etc/passwd"})
    with pytest.raises(ValueError, match="between 1 and 500"):
        await adapter.query("/report/simple/organic/keywords", {"per_page": 501})

    assert http.calls == []


@pytest.mark.asyncio
async def test_keys_so_rsya_path_is_domain_bounded() -> None:
    http = RecordingHttp()
    adapter = KeysSoAdapter("https://api.keys.so", "secret", http=http)

    await adapter.query(
        "/report/ads/rsya/domains/example.com",
        {"page": 1, "per_page": 25, "sort": "found_at|desc"},
    )
    with pytest.raises(ValueError, match="valid DNS domains"):
        await adapter.query("/report/ads/rsya/domains/..", {})

    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_keys_so_fails_closed_without_token() -> None:
    adapter = KeysSoAdapter("https://api.keys.so", "", http=RecordingHttp())
    with pytest.raises(ProviderError, match="not configured"):
        await adapter.query("/limits/all", {})


@pytest.mark.asyncio
async def test_keys_so_coalesces_identical_concurrent_reports() -> None:
    http = RecordingHttp({"limit": 100})
    adapter = KeysSoAdapter("https://api.keys.so", "secret", http=http)

    first, second = await asyncio.gather(
        adapter.query("/limits/all", {}),
        adapter.query("/limits/all", {}),
    )

    assert first == second == {"limit": 100}
    assert first is not second
    assert len(http.calls) == 1
