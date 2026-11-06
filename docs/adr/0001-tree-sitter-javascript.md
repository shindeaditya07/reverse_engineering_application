# 0001. Parse JavaScript with tree-sitter, one grammar

- Status: accepted
- Date: 2026-11-06

## Context

Code Analysis (FR-3) must find routes registered in loops and behind conditions, which a
line-pattern finder cannot (the grep baseline and Discovery both miss them). The spec already
names tree-sitter as the parser (section 9). The pilot is Node/Express, and CommonJS-only is
the v1 scope (not yet confirmed by the reviewer).

## Decision

Add `tree-sitter` and `tree-sitter-javascript`, both pinned in `uv.lock`. Analyse `.js` and
`.cjs` files only. If the parser reports any error in a file, skip the whole file and store an
Unknown claim saying so, instead of analysing a tree the parser had to guess at. Record the
parser versions in each committed result.

## Consequences

- Wheels only, no compiler needed at install. Install scripts are not involved (TST-1.6 is
  about the legacy app's dependencies, not the platform's).
- A newer syntax the grammar version cannot read costs a whole file. That is visible as an
  Unknown claim, not a silent omission (CLM-1.7).
- TypeScript needs a second grammar; that is a separate decision when the pilot app needs it.
- Results are tied to the grammar version, so a bump needs a re-run.
