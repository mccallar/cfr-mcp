"""Client behaviour with mocked transport: dates, errors, refusal, caching."""

import pytest
import respx
from conftest import fixture_text
from httpx import Response

from cfr_mcp.cache import Cache
from cfr_mcp.citations import parse
from cfr_mcp.client import BASE_URL, ECFRClient, ECFRError


@pytest.fixture
def client(tmp_path):
    return ECFRClient(Cache(tmp_path / "cache"))


@respx.mock(base_url=BASE_URL)
async def test_latest_date_from_titles(respx_mock, client):
    respx_mock.get("/api/versioner/v1/titles.json").respond(
        text=fixture_text("titles.json")
    )
    assert await client.latest_date_for_title(1) == "2026-08-10"
    assert await client.latest_date_for_title(21) == "2026-08-27"


@respx.mock(base_url=BASE_URL)
async def test_unknown_title_is_readable_error(respx_mock, client):
    respx_mock.get("/api/versioner/v1/titles.json").respond(
        text=fixture_text("titles.json")
    )
    with pytest.raises(ECFRError, match="Unknown CFR title"):
        await client.latest_date_for_title(99)


@respx.mock(base_url=BASE_URL)
async def test_404_becomes_readable_error(respx_mock, client):
    respx_mock.get("/api/versioner/v1/titles.json").respond(
        text=fixture_text("titles.json")
    )
    respx_mock.get(url__regex=r".*/full/.*").respond(404)
    with pytest.raises(ECFRError, match="valid issue date"):
        await client.full_xml(parse("1 CFR 2.6"))


async def test_title_level_xml_refused_without_network(client):
    # No respx mock: any HTTP attempt would error loudly.
    with pytest.raises(ECFRError, match="Refusing a title-level XML request"):
        await client.full_xml(parse("Title 40"))


@respx.mock(base_url=BASE_URL)
async def test_bad_date_rejected_before_any_request(respx_mock, client):
    with pytest.raises(ECFRError, match="YYYY-MM-DD"):
        await client.structure(1, date="last tuesday")
    assert not respx_mock.calls


@respx.mock(base_url=BASE_URL)
async def test_cache_hit_skips_http(respx_mock, client):
    route = respx_mock.get("/api/versioner/v1/titles.json").respond(
        text=fixture_text("titles.json")
    )
    await client.titles()
    await client.titles()
    assert route.call_count == 1


@respx.mock(base_url=BASE_URL)
async def test_cache_write_failure_never_breaks_lookup(
    respx_mock, tmp_path, monkeypatch
):
    import pathlib

    cache = Cache(tmp_path / "cache")

    def boom(self, *args, **kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    client = ECFRClient(cache)
    respx_mock.get("/api/versioner/v1/titles.json").respond(
        text=fixture_text("titles.json")
    )
    data = await client.titles()
    assert data["titles"]


@respx.mock(base_url=BASE_URL)
async def test_retry_then_success_on_5xx(respx_mock, client):
    route = respx_mock.get("/api/admin/v1/agencies.json")
    route.side_effect = [Response(503), Response(200, text='{"agencies": []}')]
    data = await client.agencies()
    assert data == {"agencies": []}
    assert route.call_count == 2
