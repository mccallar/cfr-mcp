# Manual test log — Phase 3 live integration

2026-08-29, against the live eCFR API. Tools were exercised at the tool-call
surface (the exact async functions MCP dispatches to), with arguments chosen
as an assistant would choose them. Outputs below are summarized; sizes are
exact.

## 1. "What does 21 CFR 101.9(c) require?"

`lookup_citation("21 CFR 101.9(c)")`

- First run returned the full (c) block: correct text, but **35,281 chars —
  violated the output cap invariant**. Fixed: an oversized paragraph now
  returns its opening text plus a sub-paragraph list. Re-run: 3,340 chars,
  begins with the correct "(c) The declaration of nutrition information…"
  text and ends "Sub-paragraphs available: (1)…(9). Request a deeper
  citation like 101.9(c)(1)". ✅

## 2. "Search the CFR for 'per- and polyfluoroalkyl'"

`search_regulations("per- and polyfluoroalkyl", limit=5)`

- 1,268 chars. "72 result(s)… showing 5". Real citations (40 CFR 141.901,
  705.1, 372.29, 705.3) with headings and clean snippets, no HTML. ✅

## 3. "Where does 'asbestos' appear in the CFR?"

`where_does_term_appear("asbestos")`

- 4,616 chars. Title-level hit counts with top-3 parts nested under each
  (e.g. Title 16 → Part 1304 Ban of Consumer Patching Compounds…). First
  run leaked `<strong>` tags inside part headings (the counts endpoint
  highlights the query term); fixed with the same HTML stripping used for
  search. ✅

## 4. "Show the structure of 40 CFR Part 261"

`browse_structure(40, part="261")`

- 6,378 chars. Subparts A–DD with section lines, appendices I–IX at the
  bottom, zero body text. ✅

## 5. "Has 40 CFR 261.4 changed since 2023-01-01?"

`what_changed("40 CFR 261.4", since="2023-01-01")`

- 1,358 chars. Eleven amendment entries 2023-03-29 → 2025-03-21 with
  amendment and issue dates, plus part-261 published corrections with FR
  citations. Filter params verified on the wire
  (`part=261&issue_date[gte]=2023-01-01`). ✅

## 6. "Which CFR titles does the EPA administer?"

`list_agencies("environmental protection")`

- 93 chars: "Environmental Protection Agency
  [environmental-protection-agency] — Title(s) 2, 5, 40, 41, 48". First run
  sorted titles as strings ("2, 40, 41, 48, 5"); fixed to numeric sort. ✅

## 7. Adversarial: "Give me all of Title 40"

`lookup_citation("Title 40")`

- 124 chars, zero network calls: "'Title 40' names a whole CFR title, which
  is far too large to retrieve. Use browse_structure to navigate it, or
  name a part." Graceful refusal with guidance. ✅

## 8. Nonexistent paragraph: "21 CFR 101.9(z)(9)"

`lookup_citation("21 CFR 101.9(z)(9)")`

- First run fell back to a degenerate outline (a childless section's
  "outline" was just its heading, twice) and never said the paragraph was
  missing. Fixed: now 192 chars — "Paragraph (z)(9) does not exist in
  21 CFR 101.9. Top-level paragraphs present: (a)…(l). Request the whole
  section or one of those paragraphs." No fabrication. ✅

## Fixes made during this phase

1. Output cap now applies to paragraph-narrowed text (scenario 1); oversized
   paragraphs degrade to intro + sub-paragraph list.
2. `where_does_term_appear` strips HTML from headings (scenario 3).
3. `list_agencies` sorts titles numerically (scenario 6).
4. Missing paragraphs get an explicit not-found message listing the
   paragraphs that do exist (scenario 8).
5. `render_capped` on a huge childless section now outlines its top-level
   paragraphs instead of repeating the heading.

All five have regression tests in `tests/`.

## Phase 4 live checks

- `lookup_citation("40 CFR Part 63")` (one of the largest CFR parts): the
  streaming byte guard aborted the download at 20 MB after 18.1s with
  "Request a smaller unit — a subpart or a section — or use
  browse_structure to navigate this part." No multi-hundred-MB download,
  no dump. ✅
- `lookup_citation("40 CFR Part 261")` (mid-size, 1.5M chars of text,
  ~6 MB XML): 1.7s, degraded to an 8,009-char subpart/section outline with
  per-node sizes. ✅
