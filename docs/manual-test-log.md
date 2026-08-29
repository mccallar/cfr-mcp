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

## v0.2 live verification (2026-08-29)

- `what_changed("40 CFR 261.4", since="2023-01-01")`: 3,748 chars. Every
  amendment line now tagged with the FR rule behind it (effective-date match
  preferred, publication-date fallback — both verified on real data), and a
  deduped "Federal Register rules behind these amendments" block with
  publication/effective dates and rulemaking URLs. Matching validated 9/9
  against hand-checked FR data for this part. FR API failure degrades to
  plain history with an explicit "(cross-links unavailable)" note (tested
  via mock, 404). ✅
- `compare_versions("40 CFR 261.4", "2023-12-06", "2023-12-07")`: 7,414
  chars. First run refused the section outright — the input guard was 100k
  and 261.4 renders at 100,365 chars; raised to 500k (guards whole parts,
  admits every real section). Second run drowned real changes in
  whitespace-only table noise (the eCFR renders the same table with
  different internal whitespace on different dates); fixed by normalizing
  whitespace per paragraph unit before diffing. Final output shows exactly
  the substantive changes of the 88 FR 84710 technical corrections:
  amendment-note removals, the Acknowledgement→Acknowledgment spelling fix,
  and the rewritten (a)(25)(vi)-(vii) EEI filing requirements. ✅
- `compare_versions("40 CFR Part 261", …)`: refused at 1,483,414 chars with
  guidance to compare a section. `compare_versions("40 CFR 261.4(a)", …)`:
  paragraph narrowing works in the diff path too. ✅

## Security audit (2026-08-29)

Dependency CVEs: `pip-audit` on the frozen runtime AND dev dependency sets —
**no known vulnerabilities**. Key libs current: lxml 6.1.2, httpx 0.28.1,
mcp 2.1.1, pydantic 2.13.5.

Attack testing at the code surface:
- **XXE** (local file read `file:///etc/passwd`, SSRF external entity to
  169.254.169.254): blocked — `parse_xml` uses
  `resolve_entities=False, no_network=True`. No leak, no fetch. ✅
- **Billion-laughs** entity-expansion DoS: entities not expanded, output 10
  chars. ✅
- **Path/URL injection** via citation (title/part smuggling `../`, `?`, `%2e`,
  out-of-range titles): all rejected by the citation regex + 1–50 title check;
  cache keys are SHA256 so params can't traverse. ✅
- **max_chars abuse** (negative, zero, 1e9): degrades safely, no crash. ✅
- **ReDoS** on citation regexes: 6 crafted inputs (100k chars, unbalanced
  parens), all <1ms. ✅
- **FOUND + FIXED — paragraph-trail DoS.** `extract_paragraphs` is quadratic
  in trail length and runs synchronously on the asyncio event loop, so one
  crafted citation stalls every concurrent tool call. `21 CFR 101.9(c)`×80
  against the real 121k-char section took >5s (×200 ≈ minutes). The citation
  regex accepted unlimited paragraph groups. Fix: `MAX_PARAGRAPH_DEPTH=12` in
  `citations._paragraphs` (deepest real CFR nesting is ~6) rejects the input
  at parse time in 0.0001s; legit 6-level citations still parse. Regression
  tests in `test_citations.py`. Shipped in 0.2.1.
