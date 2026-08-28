"""MCP server exposing the US Code of Federal Regulations.

Unofficial. Retrieval only — this returns regulation text, not legal advice.
The eCFR is authoritative but unofficial; for legal research, verify against
the current official CFR, the daily Federal Register, and the LSA.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .cache import Cache
from .citations import CitationError, parse
from .client import ECFRClient, ECFRError
from .xml_parse import DEFAULT_MAX_CHARS, extract_paragraphs, parse_xml, render_capped

mcp = FastMCP("cfr")
_client: ECFRClient | None = None


def client() -> ECFRClient:
    global _client
    if _client is None:
        _client = ECFRClient(Cache())
    return _client


DISCLAIMER = (
    "\n\n---\nSource: eCFR (authoritative but unofficial). For legal research, "
    "verify against the official CFR, the daily Federal Register, and the LSA."
)


@mcp.tool()
async def lookup_citation(
    citation: Annotated[
        str, Field(description="e.g. '21 CFR 101.9', '40 CFR 261.4(b)(1)', "
                               "'40 CFR Part 261 Subpart C'")
    ],
    date: Annotated[
        str | None,
        Field(description="YYYY-MM-DD for point-in-time text. Omit for current."),
    ] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Retrieve the text of a specific CFR citation.

    Large parts return an outline of their sections instead of full text;
    follow up with a specific section citation to read it.
    """
    try:
        cit = parse(citation)
    except CitationError as exc:
        return f"Could not parse that citation. {exc}"

    if cit.is_title_only:
        return (
            f"'{citation}' names a whole CFR title, which is far too large to "
            "retrieve. Use browse_structure to navigate it, or name a part."
        )

    try:
        xml = await client().full_xml(cit, date)
    except ECFRError as exc:
        return f"Could not retrieve {cit}: {exc}"

    node = parse_xml(xml)
    if node is None:
        return f"No content found for {cit}."

    if cit.paragraphs:
        narrowed = extract_paragraphs(node.render(), cit.paragraphs)
        if narrowed:
            trail = "".join(f"({p})" for p in cit.paragraphs)
            return f"{cit.title} CFR {cit.section}{trail}\n\n{narrowed}{DISCLAIMER}"
        # Fall through rather than silently returning the wrong paragraph.

    return render_capped(node, max_chars) + DISCLAIMER


@mcp.tool()
async def search_regulations(
    query: str,
    title: Annotated[int | None, Field(description="Limit to a CFR title")] = None,
    agency: Annotated[str | None, Field(description="Agency slug from list_agencies")] = None,
    date: str | None = None,
    limit: int = 10,
) -> str:
    """Full-text search across the CFR.

    Returns citations, headings and short snippets only — never full text.
    Follow up with lookup_citation to read anything.
    """
    params: dict[str, Any] = {"per_page": min(limit, 20)}
    if title:
        params["conditions[hierarchy][title]"] = title
    if agency:
        params["conditions[agency_slugs][]"] = agency
    if date:
        params["conditions[date]"] = date

    try:
        data = await client().search(query, **params)
    except ECFRError as exc:
        return f"Search failed: {exc}"

    results = data.get("results", [])
    if not results:
        return f"No results for {query!r}."

    total = data.get("meta", {}).get("total_count", len(results))
    lines = [f"{total} result(s) for {query!r}; showing {len(results)}:", ""]
    for r in results:
        h = r.get("hierarchy_headings") or {}
        cite = r.get("hierarchy", {})
        label = f"{cite.get('title', '?')} CFR {cite.get('section') or 'Part ' + str(cite.get('part', '?'))}"
        heading = h.get("section") or h.get("part") or ""
        snippet = " ".join((r.get("full_text_excerpt") or "").split())[:280]
        lines.append(f"• {label} — {heading}\n  {snippet}")
    return "\n".join(lines) + DISCLAIMER


@mcp.tool()
async def where_does_term_appear(query: str, date: str | None = None) -> str:
    """Show which titles/chapters/parts contain a term, with hit counts.

    Cheap orientation tool: fetches no regulation text at all. Use this before
    searching when you don't know which part of the CFR governs a topic.
    """
    try:
        data = await client().counts_hierarchy(
            query, **({"conditions[date]": date} if date else {})
        )
    except ECFRError as exc:
        return f"Lookup failed: {exc}"

    buckets = data.get("children") or data.get("counts") or []
    if not buckets:
        return f"No hierarchy counts for {query!r}."
    lines = [f"Where {query!r} appears in the CFR:", ""]
    for b in buckets[:25]:
        lines.append(f"• Title {b.get('name', '?')}: {b.get('count', '?')} hit(s)")
    return "\n".join(lines)


@mcp.tool()
async def browse_structure(
    title: int,
    part: str | None = None,
    date: str | None = None,
) -> str:
    """Return the CFR hierarchy for a title (or one part) without any text."""
    try:
        data = await client().structure(title, date)
    except ECFRError as exc:
        return f"Could not load structure: {exc}"

    lines: list[str] = []

    def walk(node: dict, depth: int = 0, inside: bool = part is None) -> None:
        label = node.get("label") or node.get("identifier") or ""
        is_target = part is not None and node.get("type") == "part" and str(
            node.get("identifier")
        ) == str(part)
        show = inside or is_target
        if show and label:
            lines.append("  " * depth + label)
        if depth > 6:
            return
        for child in node.get("children") or []:
            walk(child, depth + 1 if show else depth, show)

    walk(data)
    if not lines:
        return f"No structure found for title {title}" + (f" part {part}" if part else "")
    return "\n".join(lines[:400])


@mcp.tool()
async def what_changed(
    citation: str,
    since: Annotated[str | None, Field(description="YYYY-MM-DD")] = None,
) -> str:
    """List amendment dates for a citation, plus any published corrections.

    This is the capability no other CFR tool offers: answering "has this rule
    changed since we wrote our procedure?"
    """
    try:
        cit = parse(citation)
    except CitationError as exc:
        return f"Could not parse that citation. {exc}"

    params: dict[str, Any] = {}
    if cit.part:
        params["conditions[part]"] = cit.part
    if since:
        params["conditions[issue_date][gte]"] = since

    try:
        data = await client().versions(cit.title, params)
        corrections = await client().corrections_for_title(cit.title)
    except ECFRError as exc:
        return f"Could not load version history: {exc}"

    versions = data.get("content_versions", [])
    if cit.section:
        versions = [v for v in versions if v.get("identifier") == cit.section]

    lines = [f"Amendment history for {cit}:", ""]
    if not versions:
        lines.append("No amendments found in that window.")
    for v in versions[:40]:
        lines.append(
            f"• {v.get('amendment_date', '?')} — {v.get('identifier', '')} "
            f"(issue {v.get('issue_date', '?')}) {v.get('name', '')}".rstrip()
        )

    relevant = [
        c
        for c in (corrections.get("ecfr_corrections") or [])
        if cit.part and str(cit.part) in str(c.get("cfr_references", ""))
    ]
    if relevant:
        lines += ["", "Published corrections:"]
        for c in relevant[:10]:
            lines.append(
                f"• {c.get('error_corrected', '?')}: {c.get('corrective_action', '')}"
            )
    return "\n".join(lines) + DISCLAIMER


@mcp.tool()
async def list_agencies(filter: str | None = None) -> str:
    """List federal agencies and the CFR titles/chapters they administer.

    Use this to turn a name like "EPA" into the right CFR title before searching.
    """
    try:
        data = await client().agencies()
    except ECFRError as exc:
        return f"Could not load agencies: {exc}"

    needle = (filter or "").lower()
    lines: list[str] = []

    def walk(agencies: list[dict], depth: int = 0) -> None:
        for a in agencies:
            name = a.get("name", "")
            slug = a.get("slug", "")
            refs = a.get("cfr_references") or []
            titles = sorted({str(r.get("title")) for r in refs if r.get("title")})
            if not needle or needle in name.lower() or needle in slug.lower():
                loc = f" — Title(s) {', '.join(titles)}" if titles else ""
                lines.append("  " * depth + f"{name} [{slug}]{loc}")
            walk(a.get("children") or [], depth + 1)

    walk(data.get("agencies", []))
    if not lines:
        return f"No agencies matched {filter!r}."
    return "\n".join(lines[:300])


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
