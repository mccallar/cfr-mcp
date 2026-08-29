# Security Policy

## Reporting a vulnerability

Please report security issues **privately**, not in a public issue where the
details would be visible to everyone before a fix ships.

Use GitHub's private vulnerability reporting: go to the
[Security tab](https://github.com/mccallar/cfr-mcp/security/advisories) and
click **Report a vulnerability**. This opens a private channel with the
maintainer.

Please include enough to reproduce — a citation string, tool call, or input
that triggers the problem, and what you observed.

This is a personal, non-commercial project, so there is no bounty and no
guaranteed response time, but reports are genuinely appreciated and taken
seriously.

## Supported versions

Only the latest release on PyPI is supported. Fixes ship in a new version
rather than as backports.

## Scope notes

`cfr-mcp` is a local stdio server with no authentication surface and no
network listener. It fetches from the public eCFR and Federal Register APIs
and returns text to the calling MCP client. The most relevant classes of
issue are therefore:

- Untrusted upstream content (regulation XML) reaching the parser. The XML
  parser runs with external-entity resolution and network access disabled.
- Denial-of-service through crafted tool arguments (e.g. a citation that
  makes parsing or diffing expensive). Inputs are bounded; a bypass of those
  bounds is in scope.
