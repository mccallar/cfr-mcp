# Contributing

Thanks for your interest. This is a small personal project, so a few honest
expectations up front:

- It's maintained in spare time and provided as-is. Issues and pull requests
  are welcome, but may not get a fast response, and not every request will be
  taken on.
- Every pull request is read line by line before merging. Code that runs
  inside other people's AI assistants is a supply-chain surface, so changes
  that add dependencies, touch the network client, or broaden what the server
  will fetch or return get particular scrutiny.

## Development

```bash
uv sync --extra dev
uv run pytest      # full suite, offline (fixtures only)
uv run ruff check .
```

Tests are fixture-backed and must pass without network access. If you change
behavior against the live eCFR or Federal Register API, capture a fixture from
the real response and add a test that exercises it, rather than mocking a
shape by hand.

## Scope

The server is retrieval-only: it returns the text of regulations and never
offers compliance judgment or legal advice. Please keep contributions within
that boundary, and keep every tool's output bounded (large content degrades to
an outline, never an unbounded dump).
