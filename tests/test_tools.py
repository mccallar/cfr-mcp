"""All six MCP tools against mocked transport serving real fixtures.

Every tool must return a string, stay bounded in size, and never leak
raw HTML or stack traces to the model.
"""


import respx
from conftest import fixture_text

from cfr_mcp.client import BASE_URL
from cfr_mcp.server import (
    browse_structure,
    list_agencies,
    lookup_citation,
    search_regulations,
    what_changed,
    where_does_term_appear,
)

MAX_TOOL_OUTPUT = 40_000  # chars; well under any sane context budget


def mock_titles(respx_mock):
    respx_mock.get("/api/versioner/v1/titles.json").respond(
        text=fixture_text("titles.json")
    )


@respx.mock(base_url=BASE_URL)
async def test_lookup_tiny_section(respx_mock, fresh_client):
    mock_titles(respx_mock)
    respx_mock.get(url__regex=r".*/full/2026-08-10/title-1\.xml").respond(
        text=fixture_text("section_1_2_6.xml")
    )
    out = await lookup_citation("1 CFR 2.6")
    assert isinstance(out, str)
    assert "Unrestricted use." in out
    assert "Any person may reproduce" in out
    assert "Source: eCFR" in out  # disclaimer on content-bearing output
    assert len(out) < MAX_TOOL_OUTPUT


@respx.mock(base_url=BASE_URL)
async def test_lookup_paragraph_narrowing(respx_mock, fresh_client):
    mock_titles(respx_mock)
    respx_mock.get(url__regex=r".*/full/2026-08-27/title-21\.xml").respond(
        text=fixture_text("section_21_101_9.xml")
    )
    out = await lookup_citation("21 CFR 101.9(c)(2)(i)")
    assert "21 CFR 101.9(c)(2)(i)" in out
    assert "Saturated fat" in out
    # Narrowed to the paragraph, not the whole 120k-char section.
    assert len(out) < 3_000


@respx.mock(base_url=BASE_URL)
async def test_lookup_missing_paragraph_falls_back_to_section(
    respx_mock, fresh_client
):
    mock_titles(respx_mock)
    respx_mock.get(url__regex=r".*/full/2026-08-27/title-21\.xml").respond(
        text=fixture_text("section_21_101_9.xml")
    )
    out = await lookup_citation("21 CFR 101.9(z)(9)")
    # Never fabricate: say the paragraph is missing and list what exists.
    assert "does not exist" in out
    assert "(a)" in out and "(j)" in out  # 101.9 runs (a) through (j)
    assert len(out) < MAX_TOOL_OUTPUT


@respx.mock(base_url=BASE_URL)
async def test_lookup_oversized_paragraph_is_capped(respx_mock, fresh_client):
    mock_titles(respx_mock)
    respx_mock.get(url__regex=r".*/full/2026-08-27/title-21\.xml").respond(
        text=fixture_text("section_21_101_9.xml")
    )
    # 101.9(c) alone is ~35k chars; the cap applies to every output.
    out = await lookup_citation("21 CFR 101.9(c)")
    assert len(out) < 15_000
    assert "too large" in out
    assert "Sub-paragraphs available" in out
    assert "(1)" in out  # names the drill-down targets


@respx.mock(base_url=BASE_URL)
async def test_lookup_large_subpart_degrades_to_outline(respx_mock, fresh_client):
    mock_titles(respx_mock)
    route = respx_mock.get(url__regex=r".*/full/2026-08-27/title-40\.xml")
    route.respond(text=fixture_text("subpart_40_261_A.xml"))
    out = await lookup_citation("40 CFR Part 261 Subpart A")
    assert "too large" in out
    assert "261.1" in out
    assert len(out) < MAX_TOOL_OUTPUT
    assert route.calls.last.request.url.params["subpart"] == "A"


@respx.mock(base_url=BASE_URL)
async def test_lookup_appendix_uses_full_label(respx_mock, fresh_client):
    mock_titles(respx_mock)
    route = respx_mock.get(url__regex=r".*/full/2026-08-27/title-40\.xml")
    route.respond(text=fixture_text("appendix_40_261_I.xml"))
    out = await lookup_citation("40 CFR Part 261, Appendix I")
    assert "Representative Sampling Methods" in out
    sent = route.calls.last.request.url.params["appendix"]
    assert sent == "Appendix I to Part 261"


async def test_lookup_title_only_refused_without_network(fresh_client):
    out = await lookup_citation("Title 40")
    assert "too large" in out
    assert "browse_structure" in out


async def test_lookup_unparseable_citation(fresh_client):
    out = await lookup_citation("the banana rule")
    assert "Could not parse" in out
    assert "21 CFR 101.9" in out  # error teaches the expected forms


@respx.mock(base_url=BASE_URL)
async def test_search_renders_citations_and_strips_html(respx_mock, fresh_client):
    route = respx_mock.get("/api/search/v1/results").respond(
        text=fixture_text("search_results.json")
    )
    out = await search_regulations("nutrition labeling", limit=3)
    assert "671 result(s)" in out
    assert "9 CFR 317.309" in out
    # Excerpts/headings arrive with <strong> and ellipsis spans — never leak.
    assert "<strong>" not in out and "<span" not in out
    assert route.calls.last.request.url.params["per_page"] == "3"
    assert len(out) < MAX_TOOL_OUTPUT


@respx.mock(base_url=BASE_URL)
async def test_search_filters_use_bare_param_names(respx_mock, fresh_client):
    route = respx_mock.get("/api/search/v1/results").respond(
        text=fixture_text("search_results.json")
    )
    await search_regulations(
        "labeling", title=21, agency="food-and-drug-administration"
    )
    params = route.calls.last.request.url.params
    # conditions[...] style 400s on the real API (fixtures/NOTES.md).
    assert params["hierarchy[title]"] == "21"
    assert params["agency_slugs[]"] == "food-and-drug-administration"


@respx.mock(base_url=BASE_URL)
async def test_where_does_term_appear(respx_mock, fresh_client):
    respx_mock.get("/api/search/v1/counts/hierarchy").respond(
        text=fixture_text("counts_hierarchy.json")
    )
    out = await where_does_term_appear("asbestos")
    assert "Title 5" in out
    assert "hit(s)" in out
    assert "None" not in out
    assert len(out) < MAX_TOOL_OUTPUT


@respx.mock(base_url=BASE_URL)
async def test_browse_structure(respx_mock, fresh_client):
    mock_titles(respx_mock)
    respx_mock.get(url__regex=r".*/structure/2026-08-10/title-1\.json").respond(
        text=fixture_text("structure_title1.json")
    )
    out = await browse_structure(1)
    assert "Chapter I" in out
    assert "Administrative Committee of the Federal Register" in out
    assert len(out) < MAX_TOOL_OUTPUT


@respx.mock(base_url=BASE_URL)
async def test_what_changed_filters_and_renders(respx_mock, fresh_client):
    versions_route = respx_mock.get(
        url__regex=r".*/versions/title-1\.json"
    ).respond(text=fixture_text("versions_filtered.json"))
    respx_mock.get(url__regex=r".*/corrections/title/1\.json").respond(
        text=fixture_text("corrections.json")
    )
    out = await what_changed("1 CFR 2.2", since="2020-01-01")
    params = versions_route.calls.last.request.url.params
    assert params["part"] == "2"
    assert params["issue_date[gte]"] == "2020-01-01"
    assert "2.2" in out
    assert "2015-12-18" in out  # amendment_date of the 2.2 entry


@respx.mock(base_url=BASE_URL)
async def test_what_changed_lists_corrections(respx_mock, fresh_client):
    respx_mock.get(url__regex=r".*/versions/title-21\.json").respond(
        json={"content_versions": []}
    )
    respx_mock.get(url__regex=r".*/corrections/title/21\.json").respond(
        text=fixture_text("corrections_21.json")
    )
    out = await what_changed("21 CFR Part 558")
    assert "Published corrections:" in out
    assert "558.600" in out


@respx.mock(base_url=BASE_URL)
async def test_what_changed_no_amendments(respx_mock, fresh_client):
    respx_mock.get(url__regex=r".*/versions/title-1\.json").respond(
        json={"content_versions": []}
    )
    respx_mock.get(url__regex=r".*/corrections/title/1\.json").respond(
        text=fixture_text("corrections.json")
    )
    out = await what_changed("1 CFR 2.6", since="2026-01-01")
    assert "No amendments" in out


@respx.mock(base_url=BASE_URL)
async def test_list_agencies_filter(respx_mock, fresh_client):
    respx_mock.get("/api/admin/v1/agencies.json").respond(
        text=fixture_text("agencies.json")
    )
    out = await list_agencies("environmental protection")
    assert "Environmental Protection Agency" in out
    assert "environmental-protection-agency" in out
    assert len(out) < MAX_TOOL_OUTPUT


@respx.mock(base_url=BASE_URL)
async def test_api_error_returned_as_string(respx_mock, fresh_client):
    mock_titles(respx_mock)
    respx_mock.get(url__regex=r".*/full/.*").respond(404)
    out = await lookup_citation("1 CFR 999.1")
    assert isinstance(out, str)
    assert "Could not retrieve" in out
    assert "valid issue date" in out  # self-correction hint for the model


async def test_all_six_tools_are_registered():
    from cfr_mcp.server import mcp

    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "lookup_citation",
        "search_regulations",
        "where_does_term_appear",
        "browse_structure",
        "what_changed",
        "list_agencies",
    }
