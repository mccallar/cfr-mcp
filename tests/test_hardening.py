"""Phase 4 hardening: reserved titles, date edges, size guard, concurrency."""

import asyncio

import pytest
import respx
from conftest import fixture_text

from cfr_mcp.cache import Cache
from cfr_mcp.client import BASE_URL, ECFRClient, ECFRError
from cfr_mcp.server import lookup_citation


def mock_titles(respx_mock):
    respx_mock.get("/api/versioner/v1/titles.json").respond(
        text=fixture_text("titles.json")
    )


@respx.mock(base_url=BASE_URL)
async def test_reserved_title_35(respx_mock, fresh_client):
    mock_titles(respx_mock)
    out = await lookup_citation("35 CFR 1.1")
    assert "reserved" in out
    assert "no regulations" in out


@respx.mock(base_url=BASE_URL)
async def test_reserved_title_raises_in_client(respx_mock, tmp_path):
    mock_titles(respx_mock)
    client = ECFRClient(Cache(tmp_path / "cache"))
    with pytest.raises(ECFRError, match="reserved"):
        await client.latest_date_for_title(35)


class TestDateEdges:
    @respx.mock(base_url=BASE_URL)
    async def test_pre_2017_date(self, respx_mock, fresh_client):
        out = await lookup_citation("1 CFR 2.6", date="2015-06-01")
        assert "point-in-time data begins" in out
        assert "govinfo.gov" in out
        assert not respx_mock.calls  # rejected before any request

    @respx.mock(base_url=BASE_URL)
    async def test_future_date(self, respx_mock, fresh_client):
        out = await lookup_citation("1 CFR 2.6", date="2099-01-01")
        assert "future" in out
        assert not respx_mock.calls

    @respx.mock(base_url=BASE_URL)
    async def test_malformed_date(self, respx_mock, fresh_client):
        out = await lookup_citation("1 CFR 2.6", date="last tuesday")
        assert "YYYY-MM-DD" in out
        assert not respx_mock.calls

    @respx.mock(base_url=BASE_URL)
    async def test_floor_date_itself_is_accepted(self, respx_mock, tmp_path):
        client = ECFRClient(Cache(tmp_path / "cache"))
        respx_mock.get(url__regex=r".*/full/2017-01-03/title-1\.xml").respond(
            text=fixture_text("section_1_2_6.xml")
        )
        from cfr_mcp.citations import parse

        xml = await client.full_xml(parse("1 CFR 2.6"), date="2017-01-03")
        assert "Unrestricted use" in xml


@respx.mock(base_url=BASE_URL)
async def test_oversized_response_refused(respx_mock, tmp_path):
    client = ECFRClient(Cache(tmp_path / "cache"), max_response_bytes=1_000)
    respx_mock.get(url__regex=r".*/full/.*").respond(text="x" * 5_000)
    from cfr_mcp.citations import parse

    with pytest.raises(ECFRError, match="Request a smaller unit"):
        await client.full_xml(parse("1 CFR 2.6"), date="2020-01-06")
    # And nothing partial was cached.
    assert not list((tmp_path / "cache").glob("*.body"))


@respx.mock(base_url=BASE_URL)
async def test_ten_parallel_lookups(respx_mock, fresh_client):
    """Semaphore holds and concurrent same-key cache writes don't corrupt."""
    mock_titles(respx_mock)
    respx_mock.get(url__regex=r".*/full/2026-08-10/title-1\.xml").respond(
        text=fixture_text("section_1_2_6.xml")
    )
    outs = await asyncio.gather(
        *(lookup_citation("1 CFR 2.6") for _ in range(10))
    )
    assert len(outs) == 10
    assert all(o == outs[0] for o in outs)
    assert "Unrestricted use." in outs[0]
    # Every cached body has its meta twin (write order: body first).
    cache_dir = fresh_client._cache.dir
    bodies = {p.stem for p in cache_dir.glob("*.body")}
    metas = {p.stem for p in cache_dir.glob("*.meta")}
    assert bodies == metas


def test_version_flag(capsys, monkeypatch):
    from cfr_mcp.server import main

    monkeypatch.setattr("sys.argv", ["cfr-mcp", "--version"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "cfr-mcp" in capsys.readouterr().out


def test_help_flag(capsys, monkeypatch):
    from cfr_mcp.server import main

    monkeypatch.setattr("sys.argv", ["cfr-mcp", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "stdio" in capsys.readouterr().out
