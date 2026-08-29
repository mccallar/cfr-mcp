import pathlib

import pytest

from cfr_mcp import server
from cfr_mcp.cache import Cache
from cfr_mcp.client import ECFRClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def fresh_client(tmp_path):
    """An ECFRClient with an isolated cache, installed as the server's client."""
    client = ECFRClient(Cache(tmp_path / "cache"))
    old = server._client
    server._client = client
    yield client
    server._client = old
