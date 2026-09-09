from __future__ import annotations

import csv
import io
import json
import sqlite3

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_server import bearer, configuration, connection

from zai_keysso import reports
from zai_keysso.server import AdmittedHttpClient, create_server
from zai_keysso.transport import ProviderRateLimited, ProviderResponseError


@pytest.fixture(scope="module")
def key_pair():
    return RSAKeyPair.generate()


def page(number, total=3, size=2):
    return {
        "current_page": number,
        "per_page": size,
        "last_page": max(1, (total + size - 1) // size),
        "total": total,
        "data": [
            {"word": f"keyword-{i}", "pos": i + 1}
            for i in range((number - 1) * size, min(number * size, total))
        ],
    }


class Pages:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    async def query(self, path, params):
        self.calls.append((path, params))
        item = next(self.payloads)
        if isinstance(item, Exception):
            raise item
        return item

    def factory(self, store, execution_id, actor, delegated):
        owner = self

        class Http(AdmittedHttpClient):
            async def request_json(self, method, url, **kwargs):
                await self._admit_attempt(1)
                return await owner.query(url, kwargs["params"])

        return Http(store, execution_id, actor, delegated)


async def collect(payloads, **kwargs):
    adapter = Pages(payloads)
    result = await reports.collect_report(
        adapter,
        "/report/simple/organic/keywords",
        {"domain": "example.com"},
        start_page=kwargs.get("start_page", 1),
        max_pages=kwargs.get("max_pages", 5),
        page_size=2,
        output=kwargs.get("output", "json"),
    )
    return result, adapter


async def test_pages_provenance_and_exact_end_of_report():
    result, adapter = await collect([page(1), page(2)])
    assert [v[1]["page"] for v in adapter.calls] == [1, 2]
    assert result["complete"] is True
    assert result["row_count"] == result["total_reported"] == 3
    assert result["source"]["included_pages"] == [1, 2]
    assert result["next_page"] is None


async def test_capped_sample_and_late_start_never_claim_complete():
    result, _ = await collect([page(1)], max_pages=1)
    assert result["complete"] is False and result["next_page"] == 2
    result, _ = await collect([page(2)], start_page=2)
    assert result["complete"] is False and result["stop_reason"] == "end_of_report"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"total": None}, "missing_pagination_metadata"),
        ({"current_page": 2}, "pagination_mismatch"),
        ({"per_page": 3}, "pagination_mismatch"),
        ({"last_page": 90}, "inconsistent_pagination_metadata"),
        ({"data": []}, "inconsistent_pagination_metadata"),
    ],
)
async def test_missing_or_inconsistent_metadata_is_not_full_report(mutation, reason):
    result, adapter = await collect([{**page(1), **mutation}])
    assert result["complete"] is False and result["stop_reason"] == reason
    assert len(adapter.calls) == 1


async def test_total_change_and_repeated_page_stop_without_appending_second_page():
    result, _ = await collect([page(1), page(2, total=4)])
    assert result["stop_reason"] == "report_changed" and result["row_count"] == 2
    result, _ = await collect([page(1), {**page(2), "data": page(1)["data"]}])
    assert result["stop_reason"] == "repeated_page" and result["row_count"] == 2


async def test_byte_budget_does_not_silently_drop_rows(monkeypatch):
    monkeypatch.setattr(reports, "MAX_BYTES", 90)
    result, adapter = await collect([page(1), page(2)])
    assert result["stop_reason"] == "byte_limit"
    assert result["next_page"] == 2 and result["row_count"] == 2
    assert result["source"]["requested_pages"] == [1, 2]
    assert len(adapter.calls) == 2


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": ["bad"]}, {"data": [{}, {}, {}]}])
async def test_malformed_provider_rows_are_rejected(payload):
    with pytest.raises(ProviderResponseError):
        await collect([payload])


async def test_csv_preserves_unicode_missing_fields_and_escapes_formulas():
    payload = page(1, total=2)
    payload["data"] = [
        {"word": '=HYPERLINK("https://example.com")', "url": "тест,страница"},
        {"word": "ordinary", "pos": 0, "nested": {"a": [1, 2]}, "password": "synthetic-column-secret"},
    ]
    result, _ = await collect([payload], output="csv")
    rows = list(csv.DictReader(io.StringIO(result["csv"])))
    assert rows[0]["word"].startswith("'=")
    assert rows[0]["url"] == "тест,страница" and rows[0]["pos"] == ""
    assert rows[1]["pos"] == "0" and json.loads(rows[1]["nested"]) == {"a": [1, 2]}
    assert "rows" not in result and result["complete"]
    assert "synthetic-column-secret" not in result["csv"]


@pytest.mark.parametrize("kwargs", [{"max_pages": 6}, {"page_size": 501}, {"start_page": 0}])
async def test_invalid_bounds_do_not_dispatch(tmp_path, key_pair, kwargs):
    source = Pages([])
    config = configuration(tmp_path, key_pair, auth_mode="operator")
    async with Client(create_server(config, transport="stdio", http_factory=source.factory)) as client:
        with pytest.raises(ToolError, match="validation_failed"):
            await client.call_tool(
                "keysso_domain_report", {"report": "keywords", "domain": "example.com", **kwargs}
            )
    assert source.calls == []


async def test_new_tool_delegation_is_bound_to_name_arguments_and_nonce(tmp_path, key_pair):
    args = {
        "report": "keywords",
        "domain": "example.com",
        "base": "msk",
        "sort": None,
        "start_page": 1,
        "max_pages": 2,
        "page_size": 2,
        "output": "json",
    }
    source = Pages([page(1), page(2)])
    config = configuration(tmp_path, key_pair)
    server = create_server(config, http_factory=source.factory)
    async with connection(server, bearer(key_pair, args, tool="keys_so_query")) as client:
        with pytest.raises(ToolError, match="provider_disabled"):
            await client.call_tool("keysso_domain_report", args)
    token = bearer(key_pair, args, tool="keysso_domain_report")
    async with connection(server, token) as client:
        assert (await client.call_tool("keysso_domain_report", args)).data["complete"]
    async with connection(create_server(config, http_factory=source.factory), token) as client:
        with pytest.raises(ToolError, match="provider_disabled"):
            await client.call_tool("keysso_domain_report", args)
    assert len(source.calls) == 2
    with sqlite3.connect(config.state_path) as database:
        assert database.execute("select count(*) from attempts").fetchone()[0] == 2


async def test_later_page_429_preserves_account_cooldown(tmp_path, key_pair):
    source = Pages([page(1), ProviderRateLimited("synthetic-secret", retry_after_seconds=60)])
    config = configuration(tmp_path, key_pair, auth_mode="operator")
    async with Client(create_server(config, transport="stdio", http_factory=source.factory)) as client:
        args = {"report": "keywords", "domain": "example.com", "max_pages": 2, "page_size": 2}
        with pytest.raises(ToolError, match="provider_rate_limited") as exc:
            await client.call_tool("keysso_domain_report", args)
        assert "synthetic-secret" not in str(exc.value)
        with pytest.raises(ToolError, match="provider_rate_limited"):
            await client.call_tool("keysso_domain_report", args)
    assert len(source.calls) == 2


async def test_comparison_uses_included_excluded_domains_and_same_secret_redaction(tmp_path, key_pair):
    config = configuration(tmp_path, key_pair, auth_mode="operator")
    payload = page(1, total=1, size=100)
    payload["data"][0]["word"] = config.provider_token
    source = Pages([payload])
    async with Client(create_server(config, transport="stdio", http_factory=source.factory)) as client:
        result = (
            await client.call_tool(
                "keysso_compare_domains",
                {
                    "include": ["EXAMPLE.COM"],
                    "exclude": ["other.example"],
                    "output": "csv",
                },
            )
        ).data
        with pytest.raises(ToolError, match="validation_failed"):
            await client.call_tool(
                "keysso_compare_domains", {"include": ["a.example,b.example"], "exclude": []}
            )
    assert source.calls[0][1]["incl"] == "example.com"
    assert source.calls[0][1]["excl"] == "other.example"
    assert config.provider_token not in json.dumps(result)
    assert "***redacted***" in result["csv"]


@pytest.mark.parametrize("secret", ['ab"cd', "ab\\cd", "=synthetic-credential"])
async def test_literal_secret_redacted_before_csv_escaping(tmp_path, key_pair, secret):
    config = configuration(tmp_path, key_pair, auth_mode="operator", provider_token=secret)
    payload = page(1, total=1, size=100)
    payload["data"] = [{"query": secret, "nested": {"value": secret}, secret: "safe"}]
    source = Pages([payload])
    async with Client(create_server(config, transport="stdio", http_factory=source.factory)) as client:
        result = await client.call_tool(
            "keysso_domain_report", {"report": "keywords", "domain": "example.com", "output": "csv"}
        )
    content = result.data
    parsed = list(csv.DictReader(io.StringIO(content["csv"])))
    assert parsed[0]["query"] == "***redacted***"
    assert json.loads(parsed[0]["nested"])["value"] == "***redacted***"
    assert secret not in parsed[0]
