# Fixture capture notes — real API vs. code assumptions

Captured 2026-08-29 from live ecfr.gov. Issue dates used: title 1 → 2026-08-10,
title 21 → 2026-08-27, title 40 → 2026-08-27.

## Discrepancies (code fixes needed in Phase 2)

1. **Versions filter params are NOT `conditions[...]`.**
   `GET /api/versioner/v1/versions/title-1.json?conditions[part]=2` → HTTP 400
   "Found unpermitted parameter: :conditions". The working forms are bare:
   `?part=2` and `?issue_date[gte]=2020-01-01` (see `versions_filtered.json`).
   → Fix `what_changed` in `server.py` (`conditions[part]`,
   `conditions[issue_date][gte]`).
   Version entries DO include `amendment_date`, `issue_date`, `identifier`,
   plus `date`, `name`, `part`, `subpart`, `title`, `type`
   (`section`|`appendix`), `substantive`, `removed`.

2. **Appendix param needs the full label, not the short identifier.**
   `?part=261&appendix=I` → 404. `?part=261&appendix=Appendix I to Part 261`
   → 200. Appendix identifiers in versions/structure use the same full-label
   form. → Fix `Citation.as_params()` to expand `appendix="I"` into
   `"Appendix {app} to Part {part}"`.

3. **Appendix XML root is `DIV9`.** `xml_parse._DIV` matches `^DIV[1-8]$`
   only, so `parse_xml` returns None for any appendix. → Widen to `DIV[1-9]`.
   Observed DIV levels: DIV5=PART, DIV6=SUBPART, DIV8=SECTION, DIV9=APPENDIX.

4. **`counts/hierarchy` response shape.** Top level:
   `{count: {value, relation}, max_score, shown_count, children: [...]}`.
   Children have `level` ('title', ...), `hierarchy` ('5'),
   `hierarchy_heading` ('Title 5'), `heading` ('Administrative Personnel'),
   `count` (int), `max_score`, nested `children`. The code's
   `b.get('name')` key does not exist → use `hierarchy_heading` + `heading`.
   Note: intermediate children can have `hierarchy_heading: null` (e.g. a
   subtitle level pass-through node).

5. **Search excerpts and headings embed HTML.** `full_text_excerpt` contains
   `<strong>` and `<span class="elipsis">…</span>`; `headings.*` also carry
   `<strong>`. → Strip tags before rendering. Confirmed keys otherwise:
   `results[].hierarchy.{title,part,section,...}` (string values, can be
   null), `hierarchy_headings`, `headings`, `full_text_excerpt`,
   `meta.total_count` / `current_page` / `total_pages` / `max_score`.

6. **Corrections matching.** `ecfr_corrections[].cfr_references[]` is a list
   of `{cfr_reference: "21 CFR 558.600", hierarchy: {title, chapter, ...,
   part, section}}`. The scaffold's substring match over `str(...)` works by
   accident but should use `hierarchy.part`. Also present: `fr_citation`,
   `year`, `last_modified`. Title 1 has zero corrections
   (`corrections.json` is the empty-list shape; `corrections_21.json` is
   non-empty).

## Confirmed-as-assumed

- `titles.json`: `titles[]` with `number` (int), `latest_issue_date`,
  `up_to_date_as_of`, `latest_amended_on`, `reserved` (bool), `name`.
  Title 35 has `reserved: true` and `latest_issue_date: null` — the
  latest-date resolver must handle the nulls.
- `structure/{date}/title-1.json`: nodes are `{identifier, label,
  label_level, label_description, reserved, type, size, children,
  descendant_range}`; `type` is lowercase ('title', 'chapter', 'part', ...).
  Matches `browse_structure`'s walk.
- `agencies.json`: `{agencies: [{name, short_name, display_name, slug,
  children, cfr_references: [{title, chapter}]}]}`. Matches `list_agencies`.
- Section XML: root can be the DIV8 itself (single-section fetch) — 1 CFR 2.6
  really is one paragraph (416 bytes). Part fetch root is DIV5 with
  AUTH/SOURCE siblings of DIV8 children; `hierarchy_metadata` attribute
  carries escaped JSON (ignore).
- `search/v1/results` params `query`, `per_page` work as used.

## Fixture inventory

| file | endpoint |
|---|---|
| titles.json | /api/versioner/v1/titles.json |
| section_1_2_6.xml | full/2026-08-10/title-1.xml?part=2&section=2.6 |
| section_21_101_9.xml | full/2026-08-27/title-21.xml?part=101&section=101.9 |
| part_1_2.xml | full/2026-08-10/title-1.xml?part=2 |
| subpart_40_261_A.xml | full/2026-08-27/title-40.xml?part=261&subpart=A |
| appendix_40_261_I.xml | full/2026-08-27/title-40.xml?part=261&appendix=Appendix I to Part 261 |
| search_results.json | /api/search/v1/results?query=nutrition+labeling&per_page=3 |
| counts_hierarchy.json | /api/search/v1/counts/hierarchy?query=asbestos |
| structure_title1.json | /api/versioner/v1/structure/2026-08-10/title-1.json |
| versions.json | /api/versioner/v1/versions/title-1.json |
| versions_filtered.json | versions/title-1.json?part=2&issue_date[gte]=2020-01-01 |
| agencies.json | /api/admin/v1/agencies.json |
| corrections.json | /api/admin/v1/corrections/title/1.json (empty list) |
| corrections_21.json | /api/admin/v1/corrections/title/21.json |
