import pytest

from cfr_mcp.citations import Citation, CitationError, parse


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("21 CFR 101.9", Citation(title=21, part="101", section="101.9")),
        ("49 CFR 172.101", Citation(title=49, part="172", section="172.101")),
        ("1 CFR 2.6", Citation(title=1, part="2", section="2.6")),
        ("21 cfr 101.9", Citation(title=21, part="101", section="101.9")),
        ("21 C.F.R. 101.9", Citation(title=21, part="101", section="101.9")),
        ("21 CFR § 101.9", Citation(title=21, part="101", section="101.9")),
        ("  21  CFR   101.9  ", Citation(title=21, part="101", section="101.9")),
    ],
)
def test_sections(raw, expected):
    assert parse(raw) == expected


def test_paragraph_trail():
    c = parse("40 CFR 261.4(b)(1)(ii)")
    assert c.title == 40
    assert c.section == "261.4"
    assert c.paragraphs == ("b", "1", "ii")


def test_paragraphs_not_sent_to_api():
    # The API has no paragraph granularity; we fetch the section and narrow locally.
    assert "paragraph" not in parse("40 CFR 261.4(b)(1)").as_params()
    assert parse("40 CFR 261.4(b)(1)").as_params() == {
        "part": "261",
        "section": "261.4",
    }


@pytest.mark.parametrize(
    "raw",
    ["40 CFR Part 261", "40 CFR 261", "Title 40, Part 261", "40 cfr part 261"],
)
def test_parts(raw):
    c = parse(raw)
    assert c.title == 40 and c.part == "261" and c.section is None


def test_subpart():
    c = parse("40 CFR Part 261 Subpart C")
    assert c.subpart == "C" and c.part == "261"
    assert c.as_params() == {"part": "261", "subpart": "C"}


def test_appendix_roman():
    c = parse("40 CFR Part 261, Appendix VIII")
    assert c.appendix == "VIII"
    # The API keys appendices by full label — bare "VIII" 404s (see
    # tests/fixtures/NOTES.md).
    assert c.as_params() == {
        "part": "261",
        "appendix": "Appendix VIII to Part 261",
    }


def test_appendix_abbreviated():
    assert parse("40 CFR Part 261 App. A").appendix == "A"


def test_title_only():
    c = parse("Title 40")
    assert c.title == 40 and c.is_title_only


def test_lettered_part():
    assert parse("12 CFR Part 226a").part == "226a"


@pytest.mark.parametrize("raw", ["", "   ", "not a citation", "banana 12", "0 CFR 1.1", "99 CFR 1.1"])
def test_rejects(raw):
    with pytest.raises(CitationError):
        parse(raw)


def test_roundtrip_str():
    for raw in ["21 CFR 101.9", "40 CFR Part 261, Appendix VIII", "40 CFR Part 261, Subpart C"]:
        assert parse(str(parse(raw))) == parse(raw)


def test_deep_real_paragraph_nesting_is_allowed():
    # Six real levels must still parse; the cap only stops pathological trails.
    assert parse("21 CFR 101.9(c)(2)(i)(A)(1)(i)").paragraphs == (
        "c", "2", "i", "A", "1", "i",
    )


def test_absurd_paragraph_depth_is_rejected():
    # A crafted trail like 101.9(c)×200 is a DoS against extract_paragraphs
    # (quadratic, synchronous on the event loop); reject it at parse time.
    with pytest.raises(CitationError, match="Too many paragraph levels"):
        parse("21 CFR 101.9" + "(c)" * 200)
