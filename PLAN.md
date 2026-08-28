# PLAN.md — cfr-mcp: scaffold → published v0.1

Execution plan for Claude Code. Work phase by phase; do not start a phase until
the previous phase's acceptance criteria pass. Commit at the end of each phase.

## Context

The repo contains a working scaffold (~700 lines):

- `src/cfr_mcp/citations.py` — CFR citation parser. **Tested, 20 cases passing.**
- `src/cfr_mcp/client.py` — async httpx client. All endpoint paths in the
  `ENDPOINTS` dict. **Never run against the live API.**
- `src/cfr_mcp/xml_parse.py` — eCFR XML → text, with size capping.
  **Written from documented conventions, never seen real XML.**
- `src/cfr_mcp/cache.py` — disk cache. Historical dates cached forever.
- `src/cfr_mcp/server.py` — FastMCP server, six tools. **JSON key names for
  search/structure/versions/agencies responses are educated guesses.**
- `tests/test_citations.py` — parser tests (pytest).

The API: base `https://www.ecfr.gov`, no key. Services: admin
(`/api/admin/v1/...`), search (`/api/search/v1/...`), versioner
(`/api/versioner/v1/...`). Full endpoint list is in `client.py`.

## Invariants — never violate these

1. **Never request title-level XML.** `full_xml` refuses `is_title_only`
   citations; keep it that way. Some titles are hundreds of MB.
2. **Every tool output is capped.** Large content degrades to an outline with
   instructions to drill down. No tool may return unbounded text.
3. **Dates are resolved, not assumed.** Versioner routes 404 on invalid issue
   dates; always resolve current dates through `titles.json`.
4. **Cache failures never break lookups.** Cache is best-effort.
5. **Errors are returned as readable strings to the model**, not raised through
   the MCP layer, so the assistant can self-correct (e.g. bad date → explain).
6. **Retrieval only.** No tool or description may imply compliance judgment or
   legal advice. Keep the source disclaimer on content-bearing outputs.

## Phase 0 — Environment (15 min)

- [ ] `git init`, initial commit of the scaffold as-is.
- [ ] `uv sync --extra dev`
- [ ] `uv run pytest` → all citation tests pass.
- [ ] Add MIT `LICENSE` file (year, author name).
- [ ] In `client.py`, replace `YOURNAME`/`YOUR_EMAIL` in `USER_AGENT`
      (ask the human for the GitHub username and contact email).

**Accept:** pytest green, clean `git status`.

## Phase 1 — Verify API reality, capture fixtures (1–2 h)

Fetch real responses and save them under `tests/fixtures/`. Use small targets.

- [ ] `GET /api/versioner/v1/titles.json` → `fixtures/titles.json`.
      Confirm field names `number`, `latest_issue_date`, `up_to_date_as_of`.
      Fix `latest_date_for_title()` if they differ.
- [ ] `GET /api/versioner/v1/full/{date}/title-1.xml?part=2&section=2.6`
      (Title 1 is tiny) → `fixtures/section_1_2_6.xml`.
- [ ] Same for a mid-size section: `title-21 ... part=101&section=101.9`
      → `fixtures/section_21_101_9.xml`.
- [ ] A whole small part: `title-1 ... part=2` → `fixtures/part_1_2.xml`.
- [ ] An appendix and a subpart request; confirm param names
      (`appendix`, `subpart`) are what the API expects. Fix
      `Citation.as_params()` if not.
- [ ] `GET /api/search/v1/results?query=nutrition+labeling&per_page=3`
      → `fixtures/search_results.json`. Record the real shape of results,
      hierarchy fields, excerpt field, meta/total.
- [ ] `GET /api/search/v1/counts/hierarchy?query=asbestos`
      → `fixtures/counts_hierarchy.json`.
- [ ] `GET /api/versioner/v1/structure/{date}/title-1.json`
      → `fixtures/structure_title1.json`.
- [ ] `GET /api/versioner/v1/versions/title-1.json` → `fixtures/versions.json`.
      Confirm filter param names (`conditions[part]`,
      `conditions[issue_date][gte]`) actually filter; note whether the
      version entries include `amendment_date`, `issue_date`, `identifier`.
- [ ] `GET /api/admin/v1/agencies.json` → `fixtures/agencies.json`.
- [ ] `GET /api/admin/v1/corrections/title/1.json` → `fixtures/corrections.json`.
- [ ] Write `tests/fixtures/NOTES.md` documenting every place the real
      response differs from what the code assumes.

**Accept:** all fixtures on disk; NOTES.md lists discrepancies (may be empty).

## Phase 2 — Make the code match reality (2–4 h)

- [ ] Fix `xml_parse._build()` against the XML fixtures. Verify: DIV nesting,
      `TYPE`/`N` attributes, `HEAD` headings, paragraph elements, and that
      heading number-stripping works on real headings.
- [ ] Verify `extract_paragraphs` finds `(b)(1)` trails in real section text
      (fixture 21 CFR 101.9 has deep paragraph nesting — ideal test).
- [ ] Fix every guessed JSON key in `server.py` rendering loops
      (search results, structure walk, versions, agencies, corrections).
- [ ] Write fixture-backed tests (use `respx` to mock httpx against fixtures):
      - `tests/test_xml_parse.py` — parse each XML fixture; assert headings,
        section numbers, non-empty text; assert `render_capped` degrades to an
        outline when `max_chars` is tiny.
      - `tests/test_client.py` — date resolution from titles fixture; 404 →
        readable `ECFRError`; title-level XML refusal; cache hit skips HTTP.
      - `tests/test_tools.py` — call each of the six tools with mocked
        transport; assert output is a string, contains expected citation,
        and stays under the cap.
- [ ] `uv run ruff check --fix .` and resolve remaining lint.

**Accept:** full pytest suite green offline (fixtures only, no network).

## Phase 3 — Live integration with Claude Code (1 h)

- [ ] Register locally: `claude mcp add cfr -- uv run cfr-mcp`
      (or `uv run mcp dev src/cfr_mcp/server.py` for the inspector).
- [ ] Exercise each tool through the assistant and record results in
      `docs/manual-test-log.md`:
      1. "What does 21 CFR 101.9(c) require?" → correct paragraph text.
      2. "Search the CFR for 'per- and polyfluoroalkyl'" → citations + snippets.
      3. "Where does 'asbestos' appear in the CFR?" → hierarchy counts.
      4. "Show the structure of 40 CFR Part 261" → outline, no text dump.
      5. "Has 40 CFR 261.4 changed since 2023-01-01?" → amendment dates.
      6. "Which CFR titles does the EPA administer?" → Title 40 (+ others).
      7. Adversarial: "Give me all of Title 40" → graceful refusal with
         guidance, not an error or a dump.
      8. A paragraph that doesn't exist: "21 CFR 101.9(z)(9)" → falls back to
         section text, does not fabricate.
- [ ] Fix anything awkward the model trips on (tool descriptions are part of
      the product — iterate on them here).

**Accept:** all eight logged with sane transcripts.

## Phase 4 — Hardening (1–2 h)

- [ ] Title 35 is reserved: `lookup_citation("35 CFR 1.1")` must return a
      clear "reserved title" message. Add test.
- [ ] Very large part (e.g. 40 CFR 63): confirm outline degradation and
      acceptable latency; consider streaming/size guard on the raw download
      if response exceeds ~5 MB.
- [ ] Date edge cases: pre-2017 dates (point-in-time floor), future dates,
      malformed dates — each returns a helpful message. Tests.
- [ ] Concurrency: fire 10 parallel `lookup_citation` calls; semaphore holds,
      nothing corrupts the cache (meta/body write order).
- [ ] Add `--version` / `-h` handling to `main()`.

**Accept:** suite green, edge cases covered.

## Phase 5 — Publish (1–2 h; human-in-the-loop)

- [ ] README final pass: verify install block, tool table, legal section
      (1 CFR 2.6, IBR caveat, "authoritative but unofficial" disclaimer,
      no seals/no-endorsement note).
- [ ] Create GitHub repo (human), push, add topics: `mcp`, `ecfr`, `cfr`,
      `regulations`, `model-context-protocol`.
- [ ] CI: GitHub Actions workflow running ruff + pytest on 3.11/3.12/3.13.
- [ ] `uv build`; test the wheel in a clean venv: `uvx --from dist/*.whl cfr-mcp`
      starts and responds to an MCP `initialize`.
- [ ] Publish: human creates PyPI account + token; `uv publish`.
- [ ] Verify end-to-end: `uvx cfr-mcp` from PyPI works in Claude Code.
- [ ] Submit to the MCP registry / community server lists (human approves
      the listing text).
- [ ] Tag `v0.1.0`, GitHub release with a short changelog.

**Accept:** a stranger can go from README to a working `lookup_citation`
call in under five minutes.

## Explicitly out of scope for v0.1

- Hosted/remote transport (SSE/HTTP) — local stdio only.
- Any paid features, alerting, or UI.
- Fetching text of standards incorporated by reference — permanently out;
  return citations only.
- State regulations, Federal Register documents beyond corrections.

## Backlog for v0.2 (do not build now)

- Federal Register cross-links in `what_changed` (which rule caused the change).
- Rendered side-by-side diffs between two dates.
- `search_suggestions` tool using `/api/search/v1/suggestions`.
- Prebuilt vertical part-bundles (food labeling, hazmat) as MCP resources.
