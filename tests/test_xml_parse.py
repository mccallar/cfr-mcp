"""XML parsing against real eCFR fixtures (see fixtures/NOTES.md)."""

import pytest
from conftest import fixture_bytes

from cfr_mcp.xml_parse import extract_paragraphs, parse_xml, render_capped


@pytest.mark.parametrize(
    "name,div_type,number,heading",
    [
        ("section_1_2_6.xml", "SECTION", "2.6", "Unrestricted use."),
        ("section_21_101_9.xml", "SECTION", "101.9", "Nutrition labeling of food."),
        ("part_1_2.xml", "PART", "2", "GENERAL INFORMATION"),
        ("subpart_40_261_A.xml", "SUBPART", "A", "General"),
        # Appendices arrive as DIV9 with a full-label N attribute.
        (
            "appendix_40_261_I.xml",
            "APPENDIX",
            "Appendix I to Part 261",
            "Representative Sampling Methods",
        ),
    ],
)
def test_parse_fixture(name, div_type, number, heading):
    node = parse_xml(fixture_bytes(name))
    assert node is not None
    assert node.type == div_type
    assert node.number == number
    # Label prefixes ("PART 2—", "§ 2.6", "Subpart A—") are stripped.
    assert node.heading == heading
    assert node.char_count > 100
    assert node.render().strip()


def test_part_children_are_sections():
    node = parse_xml(fixture_bytes("part_1_2.xml"))
    assert [c.number for c in node.children] == [
        "2.1", "2.2", "2.3", "2.4", "2.5", "2.6",
    ]
    assert all(c.type == "SECTION" for c in node.children)


def test_outline_lists_children_without_body_text():
    node = parse_xml(fixture_bytes("part_1_2.xml"))
    outline = node.outline()
    assert "Section 2.6" in outline
    assert "Unrestricted use." in outline
    # Body text stays out of outlines.
    assert "Any person may reproduce" not in outline


def test_render_capped_degrades_to_outline():
    node = parse_xml(fixture_bytes("subpart_40_261_A.xml"))
    assert node.char_count > 100_000
    capped = render_capped(node, max_chars=2_000)
    assert "too large" in capped
    assert "261.1" in capped  # the outline names the sections
    assert len(capped) < 20_000


def test_render_capped_returns_full_text_when_small():
    node = parse_xml(fixture_bytes("section_1_2_6.xml"))
    out = render_capped(node, max_chars=12_000)
    assert "Any person may reproduce" in out
    assert "too large" not in out


@pytest.fixture(scope="module")
def text():
    return parse_xml(fixture_bytes("section_21_101_9.xml")).render()


class TestExtractParagraphs:
    """21 CFR 101.9 has (a)-(j) with nesting like (b)(2)(i)(A) — every level
    starts its own line, so blocks must end at siblings, not children."""

    def test_top_level_block_spans_its_children(self, text):
        b = extract_paragraphs(text, ("b",))
        assert b is not None and b.startswith("(b)")
        # (b)(1) definitions text lives inside the (b) block…
        assert "serving size means" in b
        # …but (c) does not.
        assert "(c) The declaration of nutrition information" not in b

    def test_nested_trail(self, text):
        b1 = extract_paragraphs(text, ("b", "1"))
        assert b1 is not None and b1.startswith("(1)")
        assert "serving size means" in b1
        assert "(2)" not in b1[:200]

    def test_deep_trail(self, text):
        c2i = extract_paragraphs(text, ("c", "2", "i"))
        assert c2i is not None and c2i.startswith("(i)")
        assert "Saturated fat" in c2i

    def test_missing_paragraph_returns_none(self, text):
        assert extract_paragraphs(text, ("z", "9")) is None

    def test_empty_trail_returns_text_unchanged(self, text):
        assert extract_paragraphs(text, ()) == text
