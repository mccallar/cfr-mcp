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

_DIV = re.compile(r"^DIV[1-8]$")
_WS = re.compile(r"[ \t]+")


@dataclass
class Node:
    type: str  # SECTION, PART, SUBPART, APPENDIX...
    number: str  # e.g. "101.9"
    heading: str
    text: str
    children: list["Node"]

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
    # Headings arrive as "§ 101.9 Nutrition labeling." — split off the number.
    number = (el.get("N") or "").strip()
    if number and heading.startswith(("§", number)):
        heading = heading.lstrip("§ ").removeprefix(number).lstrip(" .—-")

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


def extract_paragraphs(text: str, paragraphs: tuple[str, ...]) -> str | None:
    """Narrow section text to a paragraph trail like (b)(1)(ii).

    The API has no paragraph granularity, so this is done locally. Returns None
    if the paragraph cannot be located, so callers can fall back to full text
    rather than silently returning the wrong thing.
    """
    if not paragraphs:
        return text
    remaining = text
    for label in paragraphs:
        pattern = re.compile(rf"^\s*\({re.escape(label)}\)\s", re.MULTILINE)
        match = pattern.search(remaining)
        if not match:
            return None
        start = match.start()
        nxt = re.compile(rf"^\s*\([^)]+\)\s", re.MULTILINE).search(
            remaining, match.end()
        )
        remaining = remaining[start : nxt.start() if nxt else len(remaining)]
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
