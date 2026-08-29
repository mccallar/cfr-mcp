"""Turn eCFR XML into compact text, and refuse to blow up the context window.

eCFR XML nests DIV1..DIV8 elements carrying a TYPE attribute (TITLE, SUBTITLE,
CHAPTER, SUBCHAP, PART, SUBPART, SECTION, APPENDIX). Headings live in HEAD,
body text in P and FP elements.

The single most important behaviour here: when a requested chunk is too large,
return an OUTLINE of its children rather than the text. A server that dumps
80k tokens into the context on one call is worse than no server.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

# Roughly 4 chars per token; 12k chars is about 3k tokens.
DEFAULT_MAX_CHARS = 12_000

# DIV1..DIV9; appendices arrive as DIV9 (TYPE="APPENDIX").
_DIV = re.compile(r"^DIV[1-9]$")
_WS = re.compile(r"[ \t]+")


@dataclass
class Node:
    type: str  # SECTION, PART, SUBPART, APPENDIX...
    number: str  # e.g. "101.9"
    heading: str
    text: str
    children: list[Node]

    @property
    def char_count(self) -> int:
        return len(self.text) + sum(c.char_count for c in self.children)

    def outline(self, indent: int = 0) -> str:
        pad = "  " * indent
        label = f"{pad}{self.type.title()} {self.number}".rstrip()
        head = f" — {self.heading}" if self.heading else ""
        size = f"  [{self.char_count:,} chars]" if self.children else ""
        lines = [label + head + size]
        for child in self.children:
            lines.append(child.outline(indent + 1))
        return "\n".join(lines)

    def render(self) -> str:
        parts = []
        if self.heading:
            parts.append(f"{self.type.title()} {self.number} — {self.heading}".strip())
        if self.text:
            parts.append(self.text)
        for child in self.children:
            parts.append(child.render())
        return "\n\n".join(p for p in parts if p)


def _text_of(el: etree._Element) -> str:
    """Flatten an element's own paragraph text, ignoring nested DIVs."""
    chunks: list[str] = []
    for child in el:
        if _DIV.match(child.tag or ""):
            continue
        if child.tag in ("HEAD", "AUTH", "SOURCE", "CITA", "EDNOTE"):
            continue
        text = " ".join(child.itertext())
        text = _WS.sub(" ", text).strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)


def _build(el: etree._Element) -> Node:
    head_el = el.find("HEAD")
    heading = ""
    if head_el is not None:
        heading = _WS.sub(" ", " ".join(head_el.itertext())).strip()
    # Headings arrive as "§ 101.9 Nutrition labeling.", "PART 2—GENERAL
    # INFORMATION", "Subpart A—General" — split off the label prefix.
    number = (el.get("N") or "").strip()
    if number:
        prefix = re.compile(
            rf"^(?:§+\s*)?"
            rf"(?:(?:part|subpart|subchapter|chapter|subtitle|title|appendix)\s+)?"
            rf"{re.escape(number)}\s*[.:—–-]*\s*",
            re.IGNORECASE,
        )
        stripped = prefix.sub("", heading, count=1)
        heading = stripped if stripped else heading

    return Node(
        type=(el.get("TYPE") or "DIV").upper(),
        number=number,
        heading=heading,
        text=_text_of(el),
        children=[_build(c) for c in el if _DIV.match(c.tag or "")],
    )


def parse_xml(raw: str | bytes) -> Node | None:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(raw, parser=parser)
    if root is None:
        return None
    for el in root.iter():
        if _DIV.match(el.tag or ""):
            return _build(el)
    return None


_ROMAN_VALS = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_ROMAN_ONLY = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)


def _roman_to_int(s: str) -> int:
    total = 0
    vals = [_ROMAN_VALS[c] for c in s.lower()]
    for i, v in enumerate(vals):
        total += -v if i + 1 < len(vals) and v < vals[i + 1] else v
    return total


def _int_to_roman(n: int) -> str:
    out = []
    for value, sym in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
                       (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                       (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def _successors(label: str, depth: int, count: int = 3) -> list[str]:
    """The next few sibling labels after `label`: (b)->(c)(d)(e), (1)->(2)...

    Labels that read as roman numerals ('i', 'iv') are ambiguous with plain
    letters; CFR nests (a)(1)(i)(A), so treat them as roman only at depth >= 2.
    A few successors, not one, so a gap from a removed paragraph doesn't run
    the block past its real end.
    """
    if label.isdigit():
        return [str(int(label) + i + 1) for i in range(count)]
    if _ROMAN_ONLY.match(label) and (depth >= 2 or len(label) > 1):
        n = _roman_to_int(label)
        succ = [_int_to_roman(n + i + 1) for i in range(count)]
        return [s.upper() for s in succ] if label.isupper() else succ
    if len(label) == 1 and label.isalpha() and label.lower() != "z":
        return [chr(ord(label) + i + 1) for i in range(count)
                if (label.isupper() and chr(ord(label) + i + 1) <= "Z")
                or (label.islower() and chr(ord(label) + i + 1) <= "z")]
    return []


def _marker(label: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*\({re.escape(label)}\)", re.MULTILINE)


def extract_paragraphs(text: str, paragraphs: tuple[str, ...]) -> str | None:
    """Narrow section text to a paragraph trail like (b)(1)(ii).

    The API has no paragraph granularity, so this is done locally. Real eCFR
    text puts every nesting level at line start — "(b)" then "(1)" then "(i)"
    are consecutive paragraphs — so a block ends at the next SIBLING of the
    requested label or of any of its ancestors, never at its own children.

    Returns None if the paragraph cannot be located, so callers can fall back
    to full text rather than silently returning the wrong thing.
    """
    if not paragraphs:
        return text
    remaining = text
    enders: list[str] = []  # successor labels of every ancestor level
    for depth, label in enumerate(paragraphs):
        match = _marker(label).search(remaining)
        if not match:
            return None
        enders = _successors(label, depth) + enders
        end = len(remaining)
        for ender in enders:
            nxt = _marker(ender).search(remaining, match.end())
            if nxt and nxt.start() < end:
                end = nxt.start()
        remaining = remaining[match.start() : end]
    return remaining.strip()


def render_capped(node: Node, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Full text if it fits; otherwise an outline plus instructions."""
    if node.char_count <= max_chars:
        return node.render()

    return (
        f"{node.type.title()} {node.number} — {node.heading}\n\n"
        f"This is too large to return in full ({node.char_count:,} characters). "
        f"Its structure is below; request a specific section to read the text.\n\n"
        f"{node.outline()}"
    )
