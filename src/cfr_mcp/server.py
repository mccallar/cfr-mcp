"""MCP server exposing the US Code of Federal Regulations.

Unofficial. Retrieval only — this returns regulation text, not legal advice.
The eCFR is authoritative but unofficial; for legal research, verify against
the current official CFR, the daily Federal Register, and the LSA.
"""

from __future__ import annotations

import html
import re
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .cache import Cache
from .citations import CitationError, parse
from .client import ECFRClient, ECFRError
from .xml_parse import (
    DEFAULT_MAX_CHARS,
    extract_paragraphs,
    parse_xml,
    render_capped,
    top_level_paragraphs,
)

mcp = MCPServer(
    "cfr",
    instructions=(
        "Retrieval of US Code of Federal Regulations text via the eCFR API. "
        "Retrieval only: no compliance judgment or legal advice."
    ),
)
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

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Search responses embed <strong> and ellipsis spans in excerpts/headings."""
    return html.unescape(_TAG_RE.sub("", text))


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
        trail = "".join(f"({p})" for p in cit.paragraphs)
        narrowed = extract_paragraphs(node.render(), cit.paragraphs)
        if narrowed:
            if len(narrowed) <= max_chars:
                return (
                    f"{cit.title} CFR {cit.section}{trail}\n\n{narrowed}"
                    f"{DISCLAIMER}"
                )
            # A paragraph like 101.9(c) can be 35k chars on its own; the cap
            # applies to every output. Point at the sub-paragraphs instead.
            body = narrowed.split("\n", 1)[1] if "\n" in narrowed else ""
            subs = top_level_paragraphs(body)
            if subs:
                sub_list = ", ".join(f"({s})" for s, _ in subs[:30])
                return (
                    f"{cit.title} CFR {cit.section}{trail} is "
                    f"{len(narrowed):,} characters — too large to return in "
                    f"full. It begins:\n\n{narrowed[:max_chars // 4]}…\n\n"
                    f"Sub-paragraphs available: {sub_list}. Request a deeper "
                    f"citation like {cit.section}{trail}({subs[0][0]})"
                    + DISCLAIMER
                )
            return (
                f"{cit.title} CFR {cit.section}{trail}\n\n"
                f"{narrowed[:max_chars]}\n\n[Truncated at {max_chars:,} of "
                f"{len(narrowed):,} characters.]" + DISCLAIMER
            )
        # Never silently return the wrong paragraph: say it isn't there,
        # list what is, and let the model re-ask.
        paras = top_level_paragraphs(node.text)
        available = ", ".join(f"({p})" for p, _ in paras)
        return (
            f"Paragraph {trail} does not exist in {cit.title} CFR "
            f"{cit.section}. Top-level paragraphs present: "
            f"{available or 'none (the section has no lettered paragraphs)'}. "
            f"Request the whole section or one of those paragraphs."
        )

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
        params["hierarchy[title]"] = title
    if agency:
        params["agency_slugs[]"] = agency
    if date:
        params["date"] = date

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
        cite = r.get("hierarchy") or {}
        headings = r.get("headings") or {}
        if cite.get("section"):
            label = f"{cite.get('title', '?')} CFR {cite['section']}"
        elif cite.get("appendix"):
            label = f"{cite.get('title', '?')} CFR {cite['appendix']}"
        elif cite.get("part"):
            label = f"{cite.get('title', '?')} CFR Part {cite['part']}"
        else:
            label = f"Title {cite.get('title', '?')} CFR"
        heading = _strip_html(
            headings.get("section") or headings.get("appendix")
            or headings.get("part") or ""
        )
        snippet = _strip_html(r.get("full_text_excerpt") or "")
        snippet = " ".join(snippet.split())[:280]
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

    buckets = data.get("children") or []
    if not buckets:
        return f"No hierarchy counts for {query!r}."

    lines = [f"Where {query!r} appears in the CFR:", ""]

    def parts_of(node: dict) -> list[dict]:
        """Collect part-level descendants (children nest title→chapter→part)."""
        found: list[dict] = []
        for child in node.get("children") or []:
            if child.get("level") == "part" and child.get("hierarchy_heading"):
                found.append(child)
            else:
                found.extend(parts_of(child))
        return found

    for b in buckets[:25]:
        heading = _strip_html(b.get("heading") or "")
        lines.append(
            f"• {b.get('hierarchy_heading', '?')} — {heading}: "
            f"{b.get('count', '?')} hit(s)"
        )
        top = sorted(parts_of(b), key=lambda p: -(p.get("count") or 0))[:3]
        for p in top:
            lines.append(
                f"    {p.get('hierarchy_heading')} "
                f"({_strip_html(p.get('heading') or '')}): {p.get('count')}"
            )
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
        params["part"] = cit.part
    if since:
        params["issue_date[gte]"] = since

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

    def touches_part(correction: dict) -> bool:
        refs = correction.get("cfr_references") or []
        return any(
            str((r.get("hierarchy") or {}).get("part")) == str(cit.part)
            for r in refs
        )

    relevant = [
        c for c in (corrections.get("ecfr_corrections") or [])
        if cit.part and touches_part(c)
    ]
    if relevant:
        lines += ["", "Published corrections:"]
        for c in relevant[:10]:
            refs = ", ".join(
                r.get("cfr_reference", "") for r in c.get("cfr_references") or []
            )
            lines.append(
                f"• {c.get('error_corrected', '?')} ({refs}): "
                f"{c.get('corrective_action', '')} [{c.get('fr_citation', '')}]"
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
            titles = [
                str(t)
                for t in sorted({int(r["title"]) for r in refs if r.get("title")})
            ]
            if not needle or needle in name.lower() or needle in slug.lower():
                loc = f" — Title(s) {', '.join(titles)}" if titles else ""
                lines.append("  " * depth + f"{name} [{slug}]{loc}")
            walk(a.get("children") or [], depth + 1)

    walk(data.get("agencies", []))
    if not lines:
        return f"No agencies matched {filter!r}."
    return "\n".join(lines[:300])


def main() -> None:
    import argparse
    from importlib.metadata import PackageNotFoundError, version

    try:
        pkg_version = version("cfr-mcp")
    except PackageNotFoundError:
        pkg_version = "unknown"

    parser = argparse.ArgumentParser(
        prog="cfr-mcp",
        description=(
            "MCP server for the US Code of Federal Regulations (eCFR). "
            "Speaks MCP over stdio; point your MCP client at this command."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"cfr-mcp {pkg_version}"
    )
    parser.parse_args()
    mcp.run()


if __name__ == "__main__":
    main()
