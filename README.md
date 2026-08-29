# cfr-mcp

[![CI](https://github.com/mccallar/cfr-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/mccallar/cfr-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cfr-mcp)](https://pypi.org/project/cfr-mcp/)

An MCP server that gives AI assistants access to the **US Code of Federal Regulations**.

Ask "what does 21 CFR 101.9 require?" or "has 40 CFR 261 changed since 2023?" and get
the actual regulation text, with citations, instead of a plausible-sounding guess.

Unofficial community project. Not affiliated with or endorsed by the Office of the
Federal Register, NARA, or GPO, and uses no government seals or logos.

## Install

Requires Python 3.11+. No API key — the eCFR API is open.

Claude Code:

```bash
claude mcp add cfr -- uvx cfr-mcp
```

Any other MCP client:

```json
{
  "mcpServers": {
    "cfr": {
      "command": "uvx",
      "args": ["cfr-mcp"]
    }
  }
}
```

## Tools

| Tool | What it does |
|---|---|
| `lookup_citation` | Text of a citation — `21 CFR 101.9`, `40 CFR 261.4(b)(1)`, `40 CFR Part 261 Subpart C` |
| `search_regulations` | Full-text search; returns citations and snippets, never bodies |
| `where_does_term_appear` | Which titles contain a term, with hit counts. Fetches no text |
| `browse_structure` | The hierarchy of a title or part, no text |
| `what_changed` | Amendment history and published corrections for a citation |
| `list_agencies` | Maps agency names to the CFR titles they administer |

Point-in-time works throughout: pass `date` as `YYYY-MM-DD` to read the CFR as it stood.

## Design notes

**Context budget is the whole game.** The eCFR `full` endpoint returns an entire
downloadable XML document for a title-level request. Every tool here caps output and
degrades to an outline rather than dumping text into the model's context. Title-level
XML requests are refused outright.

**Dates must be resolved, not assumed.** Versioner routes 404 on dates that aren't
valid issue dates for a title, so the client resolves through `titles.json` first
rather than passing today's date blindly.

**Caching is courtesy.** The eCFR publishes no rate limit and has no key to identify
callers politely, so the client caches to disk (historical dates forever, since
point-in-time content is immutable) and self-limits concurrency. The cache lives in
`~/.cache/cfr-mcp` (respects `XDG_CACHE_HOME`); set `CFR_MCP_CACHE_DIR` to relocate it.

## Legal

Regulation text is free to reproduce. **1 CFR 2.6** states that any person may reproduce
or republish material appearing in the Federal Register, with no restrictions on what is
reproduced, who reproduces it, or where. Federal government works are also outside
copyright under 17 U.S.C. §105.

**Incorporation by reference.** Some CFR sections incorporate private standards
(ASTM, NFPA, ASHRAE) whose copyright status after incorporation remains unsettled.
The eCFR does not contain the text of those standards and neither does this server —
it returns the citation only. Obtain standards from the issuing organization or the
Office of the Federal Register reading room.

**Status of the text.** The eCFR is authoritative but unofficial. Anyone relying on it
for legal research should verify against the current official CFR, the daily Federal
Register, and the List of CFR Sections Affected (LSA).

**Not legal advice.** This is a retrieval tool. It returns the text of regulations; it
does not tell you whether you are compliant with them.

## Development

```bash
uv sync --extra dev
uv run pytest
```

MIT licensed.
