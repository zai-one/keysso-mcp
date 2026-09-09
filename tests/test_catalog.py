import json

from fastmcp import Client

from zai_keysso.adapter import ALLOWED_PARAMS, ALLOWED_PATHS, KeysSoAdapter
from zai_keysso.catalog import report_catalog
from zai_keysso.config import ServiceConfig
from zai_keysso.server import create_server


async def test_catalog_matches_policy_and_is_available_without_provider_calls(tmp_path):
    def forbidden(*args):
        raise AssertionError("Discovery must not create an HTTP client")

    server = create_server(
        ServiceConfig(provider_token="synthetic-secret", state_path=tmp_path / "state.sqlite"),
        transport="stdio",
        http_factory=forbidden,
    )
    async with Client(server) as client:
        resources = await client.list_resources()
        assert any(str(item.uri) == "keysso://reports" for item in resources)
        result = await client.read_resource("keysso://reports")
    catalog = json.loads(result[0].text)
    assert {item["path"] for item in catalog["reports"]} == ALLOWED_PATHS
    assert set(catalog["parameters"]) == ALLOWED_PARAMS
    assert "synthetic-secret" not in json.dumps(catalog)
    assert catalog == report_catalog()
    KeysSoAdapter.validate(**catalog["example"])
