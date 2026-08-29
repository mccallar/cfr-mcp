"""Parse CFR citation strings into structured components.

This is the least glamorous and most load-bearing module in the project.
Every tool that takes a human-written citation depends on it.

Handled forms:
    21 CFR 101.9
    21 CFR 101.9(c)(2)(i)
    40 CFR Part 261
    40 CFR Part 261 Subpart C
    40 CFR Part 261, Appendix VIII
    Title 40, Part 261
    49 CFR 172.101
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class CitationError(ValueError):
    """Raised when a citation string cannot be parsed."""


@dataclass(frozen=True)
class Citation:
    title: int
    part: str | None = None
    section: str | None = None
    subpart: str | None = None
    appendix: str | None = None
    paragraphs: tuple[str, ...] = field(default_factory=tuple)

    def as_params(self) -> dict[str, str]:
        """Query params for the versioner `full` endpoint.

        Note: the API returns an entire downloadable XML document for a bare
        title request, so we always send at least a part when we have one.
        Paragraphs are NOT sent -- the API has no paragraph granularity, so we
        retrieve the section and narrow locally.
        """
        params: dict[str, str] = {}
        if self.part:
            params["part"] = self.part
        if self.subpart:
            params["subpart"] = self.subpart
        if self.section:
            params["section"] = self.section
        if self.appendix:
            # The API keys appendices by their full label, e.g.
            # "Appendix VIII to Part 261" — a bare "VIII" 404s.
            params["appendix"] = f"Appendix {self.appendix} to Part {self.part}"
        return params

    @property
    def is_title_only(self) -> bool:
        return not any((self.part, self.section, self.subpart, self.appendix))

    def __str__(self) -> str:
        if self.section:
            base = f"{self.title} CFR {self.section}"
        elif self.appendix:
            base = f"{self.title} CFR Part {self.part}, Appendix {self.appendix}"
        elif self.subpart:
            base = f"{self.title} CFR Part {self.part}, Subpart {self.subpart}"
        elif self.part:
            base = f"{self.title} CFR Part {self.part}"
        else:
            base = f"Title {self.title} CFR"
        return base + "".join(f"({p})" for p in self.paragraphs)


_TITLE = r"(?:title\s+)?(?P<title>\d{1,2})"
_CFR = r"(?:\s*,?\s*(?:cfr|c\.f\.r\.))?"
# Must consume at least one character: a zero-width separator lets the regex
# backtrack and split "Title 40" into title=4, part=0.
_SEP = r"[\s,]+"

# 21 CFR 101.9(c)(2)  -- section numbers may be like 101.9, 172.101, 1.1
_SECTION_RE = re.compile(
    rf"^{_TITLE}{_CFR}{_SEP}(?:§+\s*)?"
    r"(?P<part>\d+[a-zA-Z]?)\.(?P<sec>[\w\-]+)"
    r"(?P<paras>(?:\s*\([\w]+\))*)\s*$",
    re.IGNORECASE,
)

# 40 CFR Part 261, Appendix VIII
_APPENDIX_RE = re.compile(
    rf"^{_TITLE}{_CFR}{_SEP}(?:part\s+)?(?P<part>\d+[a-zA-Z]?)"
    rf"{_SEP}app(?:endix)?\.?\s+(?P<app>[IVXLCDM]+|[A-Z0-9]+)\s*$",
    re.IGNORECASE,
)

# 40 CFR Part 261 Subpart C
_SUBPART_RE = re.compile(
    rf"^{_TITLE}{_CFR}{_SEP}(?:part\s+)?(?P<part>\d+[a-zA-Z]?)"
    rf"{_SEP}subpart\.?\s+(?P<subpart>[A-Z]{{1,3}})\s*$",
    re.IGNORECASE,
)

# 40 CFR Part 261  /  40 CFR 261
_PART_RE = re.compile(
    rf"^{_TITLE}{_CFR}{_SEP}(?:part\s+)?(?P<part>\d+[a-zA-Z]?)\s*$",
    re.IGNORECASE,
)

# Title 40  /  40 CFR
_TITLE_ONLY_RE = re.compile(rf"^{_TITLE}{_CFR}\s*$", re.IGNORECASE)

_PARA_RE = re.compile(r"\(([\w]+)\)")

# The deepest paragraph nesting the CFR uses is roughly (a)(1)(i)(A)(1)(i) —
# six levels. Anything beyond this cap is never a real citation; rejecting it
# keeps a crafted trail like "101.9(c)(c)(c)…×200" out of extract_paragraphs,
# whose matching cost is quadratic in the trail length (and runs synchronously
# on the event loop, so one bad citation would stall every concurrent call).
MAX_PARAGRAPH_DEPTH = 12


def _paragraphs(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    labels = tuple(_PARA_RE.findall(raw))
    if len(labels) > MAX_PARAGRAPH_DEPTH:
        raise CitationError(
            f"Too many paragraph levels ({len(labels)}); the CFR nests at most "
            f"about six. Cite a specific paragraph like 101.9(c)(2)(i)."
        )
    return labels


def _check_title(value: str) -> int:
    title = int(value)
    # CFR has 50 titles; title 35 is reserved and currently unused.
    if not 1 <= title <= 50:
        raise CitationError(f"CFR title must be between 1 and 50, got {title}")
    return title


def parse(citation: str) -> Citation:
    """Parse a CFR citation string. Raises CitationError on failure."""
    if not citation or not citation.strip():
        raise CitationError("Empty citation")

    text = " ".join(citation.strip().split())
    text = text.replace("\u00a7", "§")

    if m := _SECTION_RE.match(text):
        return Citation(
            title=_check_title(m["title"]),
            part=m["part"],
            section=f"{m['part']}.{m['sec']}",
            paragraphs=_paragraphs(m["paras"]),
        )

    if m := _APPENDIX_RE.match(text):
        return Citation(
            title=_check_title(m["title"]),
            part=m["part"],
            appendix=m["app"].upper(),
        )

    if m := _SUBPART_RE.match(text):
        return Citation(
            title=_check_title(m["title"]),
            part=m["part"],
            subpart=m["subpart"].upper(),
        )

    if m := _PART_RE.match(text):
        return Citation(title=_check_title(m["title"]), part=m["part"])

    if m := _TITLE_ONLY_RE.match(text):
        return Citation(title=_check_title(m["title"]))

    raise CitationError(
        f"Could not parse {citation!r}. Expected forms like "
        "'21 CFR 101.9', '40 CFR Part 261 Subpart C', "
        "'40 CFR Part 261, Appendix VIII'."
    )
